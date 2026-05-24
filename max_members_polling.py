
# -*- coding: utf-8 -*-
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
import requests

from config import (
    MAX_STATS_BOT_TOKEN,
    MAX_STATS_POLL_ENABLED,
    MAX_STATS_POLL_INTERVAL_SEC,
    MAX_STATS_REQUEST_TIMEOUT,
    MAX_STATS_BOT_API_BASE,
    MAX_STATS_SKIP_INITIAL_SNAPSHOT_NOTIFICATIONS,
)
from logging_config import setup_logger
from stats_db import (
    get_active_snapshot_members,
    has_any_snapshot_for_chat,
    insert_max_poll_run,
    mark_missing_members_inactive,
    save_member_event,
    upsert_max_member_snapshot,
)
from tg_notifications import send_max_member_notification

setup_logger()
logger = logging.getLogger(__name__)

_session = requests.Session()
_session.trust_env = False


def get_novosibirsk_now():
    tz = pytz.timezone("Asia/Novosibirsk")
    return datetime.now(tz)


def _headers() -> Dict[str, str]:
    return {
        "Authorization": MAX_STATS_BOT_TOKEN,
        "Accept": "application/json",
    }


def _get_json(path: str) -> Any:
    url = f"{MAX_STATS_BOT_API_BASE.rstrip('/')}{path}"
    resp = _session.get(url, headers=_headers(), timeout=MAX_STATS_REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _extract_chats(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("chats", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _extract_members(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("members", "items", "data", "users"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def fetch_chats() -> List[Dict[str, Any]]:
    payload = _get_json("/chats")
    chats = _extract_chats(payload)
    logger.info("MAX polling fetched %s chats", len(chats))
    return chats


def fetch_chat_members(chat_id: int) -> List[Dict[str, Any]]:
    all_members: List[Dict[str, Any]] = []
    marker: Optional[int] = None
    page = 0

    while True:
        path = f"/chats/{chat_id}/members"
        if marker is not None:
            separator = "&" if "?" in path else "?"
            path = f"{path}{separator}marker={marker}"

        payload = _get_json(path)
        members = _extract_members(payload)
        all_members.extend(members)
        page += 1

        next_marker = payload.get("marker") if isinstance(payload, dict) else None
        logger.info(
            "MAX polling fetched members page=%s chat_id=%s page_size=%s next_marker=%s total_so_far=%s",
            page, chat_id, len(members), next_marker, len(all_members)
        )

        if next_marker is None:
            break

        try:
            marker = int(next_marker)
        except Exception:
            marker = next_marker

        if not members:
            logger.warning(
                "MAX polling got marker without members for chat_id=%s marker=%s; stopping pagination",
                chat_id, marker
            )
            break

    return all_members


def _chat_id(chat: Dict[str, Any]) -> Optional[int]:
    for key in ("chat_id", "id"):
        value = chat.get(key)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _chat_title(chat: Dict[str, Any]) -> str:
    return str(chat.get("title") or chat.get("name") or f"MAX chat {chat.get('chat_id') or chat.get('id')}")


def _chat_type(chat: Dict[str, Any]) -> str:
    """
    Нормализуем тип MAX-чата для статистики.

    В MAX API поле может называться по-разному в разных ответах/версиях:
    type, chat_type, kind, dialog_type. Поэтому берем несколько возможных
    вариантов и приводим к двум значениям для нашей статистики:
      - channel
      - group

    Если API вернул неизвестный тип, сохраняем его как есть в нижнем регистре.
    Если типа нет совсем — ставим unknown, чтобы такие чаты не потерялись в БД,
    но не смешивались с каналами/группами в отчетах.
    """
    candidates = [
        chat.get("chat_type"),
        chat.get("type"),
        chat.get("kind"),
        chat.get("dialog_type"),
    ]

    nested_chat = chat.get("chat") if isinstance(chat.get("chat"), dict) else {}
    candidates.extend([
        nested_chat.get("chat_type"),
        nested_chat.get("type"),
        nested_chat.get("kind"),
        nested_chat.get("dialog_type"),
    ])

    for raw_value in candidates:
        if raw_value is None:
            continue
        value = str(raw_value).strip().lower()
        if not value:
            continue

        if value in ("channel", "public_channel", "broadcast", "broadcast_channel"):
            return "channel"
        if value in ("group", "chat", "supergroup", "private_group", "public_group", "conversation"):
            return "group"
        if "channel" in value:
            return "channel"
        if "group" in value or value == "chat":
            return "group"
        return value

    for key in ("is_channel", "channel"):
        if key in chat and isinstance(chat.get(key), bool) and chat.get(key):
            return "channel"

    for key in ("is_group", "group"):
        if key in chat and isinstance(chat.get(key), bool) and chat.get(key):
            return "group"

    return "unknown"


def _member_user_id(member: Dict[str, Any]) -> Optional[int]:
    candidates = [
        member.get("user_id"),
        (member.get("user") or {}).get("user_id") if isinstance(member.get("user"), dict) else None,
        member.get("id"),
    ]
    for value in candidates:
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _member_username(member: Dict[str, Any]) -> Optional[str]:
    user = member.get("user") if isinstance(member.get("user"), dict) else {}
    return member.get("username") or user.get("username") or user.get("nickname")


def _member_full_name(member: Dict[str, Any]) -> Optional[str]:
    user = member.get("user") if isinstance(member.get("user"), dict) else {}
    return member.get("name") or user.get("name") or user.get("full_name")


def _member_is_admin(member: Dict[str, Any]) -> Optional[bool]:
    for key in ("is_admin", "admin"):
        if key in member:
            return bool(member.get(key))
    role = str(member.get("role") or member.get("status") or "").lower()
    if role:
        return role in ("admin", "administrator", "owner", "creator")
    return None


def _member_is_creator(member: Dict[str, Any]) -> Optional[bool]:
    for key in ("is_creator", "creator", "is_owner"):
        if key in member:
            return bool(member.get(key))
    role = str(member.get("role") or member.get("status") or "").lower()
    if role:
        return role in ("owner", "creator")
    return None


def _member_status(member: Dict[str, Any]) -> Optional[str]:
    return member.get("status") or member.get("role")


def process_chat(chat: Dict[str, Any]) -> None:
    chat_id = _chat_id(chat)
    if chat_id is None:
        logger.warning("Skipping MAX chat without id: %s", json.dumps(chat, ensure_ascii=False))
        return

    chat_title = _chat_title(chat)
    chat_type = _chat_type(chat)
    poll_dt = get_novosibirsk_now()

    try:
        members = fetch_chat_members(chat_id)
        has_existing_snapshot = has_any_snapshot_for_chat(chat_id)
        snapshot = get_active_snapshot_members(chat_id)
        is_initial_snapshot = not has_existing_snapshot
        current_user_ids: List[int] = []
        new_members_count = 0
        skipped_initial_notifications_count = 0

        if is_initial_snapshot:
            logger.info(
                "MAX polling detected initial snapshot for chat_id=%s title=%s type=%s; existing members will be saved without Telegram notifications",
                chat_id,
                chat_title,
                chat_type,
            )

        for member in members:
            user_id = _member_user_id(member)
            if user_id is None:
                continue

            current_user_ids.append(user_id)
            user_username = _member_username(member)
            user_full_name = _member_full_name(member)
            is_admin = _member_is_admin(member)
            is_creator = _member_is_creator(member)
            member_status = _member_status(member)

            is_new = user_id not in snapshot

            upsert_max_member_snapshot(
                chat_id=chat_id,
                chat_title=chat_title,
                chat_type=chat_type,
                user_id=user_id,
                user_username=user_username,
                user_full_name=user_full_name,
                is_admin=is_admin,
                is_creator=is_creator,
                member_status=member_status,
                raw_member=member,
                seen_dt=poll_dt,
            )

            if is_new:
                new_members_count += 1
                save_member_event({
                    "event_dt": poll_dt,
                    "platform": "max",
                    "chat_title": chat_title,
                    "chat_type": chat_type,
                    "user_full_name": user_full_name,
                    "user_id": user_id,
                    "user_username": user_username,
                    "user_phone": None,
                    "action": "добавился",
                    "actor_name": None,
                    "actor_id": None,
                    "actor_username": None,
                    "actor_phone": None,
                    "invite_link_name": None,
                    "invite_link_url": None,
                    "invite_link_creator": None,
                    "invite_link_is_primary": None,
                    "invite_link_is_revoked": None,
                    "invite_link_expires_dt": None,
                    "chat_id": chat_id,
                    "raw_event": {"source": "max_polling", "kind": "join_detected", "chat_type": chat_type, "chat": chat, "member": member},
                })

                if is_initial_snapshot and MAX_STATS_SKIP_INITIAL_SNAPSHOT_NOTIFICATIONS:
                    skipped_initial_notifications_count += 1
                else:
                    send_max_member_notification(
                        action="добавился",
                        chat_title=chat_title,
                        chat_id=chat_id,
                        user_id=user_id,
                        user_username=user_username,
                        user_full_name=user_full_name,
                    )

        inactive_members = mark_missing_members_inactive(chat_id, current_user_ids, poll_dt=poll_dt)
        for member in inactive_members:
            save_member_event({
                "event_dt": poll_dt,
                "platform": "max",
                "chat_title": chat_title,
                "chat_type": chat_type,
                "user_full_name": member.get("user_full_name"),
                "user_id": member.get("user_id"),
                "user_username": member.get("user_username"),
                "user_phone": None,
                "action": "удалился",
                "actor_name": None,
                "actor_id": None,
                "actor_username": None,
                "actor_phone": None,
                "invite_link_name": None,
                "invite_link_url": None,
                "invite_link_creator": None,
                "invite_link_is_primary": None,
                "invite_link_is_revoked": None,
                "invite_link_expires_dt": None,
                "chat_id": chat_id,
                "raw_event": {"source": "max_polling", "kind": "leave_detected", "chat_type": chat_type, "chat": chat, "member": member.get("raw_member")},
            })

            send_max_member_notification(
                action="удалился",
                chat_title=chat_title,
                chat_id=chat_id,
                user_id=member.get("user_id"),
                user_username=member.get("user_username"),
                user_full_name=member.get("user_full_name"),
            )

        insert_max_poll_run(
            chat_id=chat_id,
            chat_title=chat_title,
            members_count=len(current_user_ids),
            status="ok",
            error_text=None,
        )
        logger.info(
            "MAX polling processed chat_id=%s title=%s type=%s current=%s new=%s removed=%s initial_snapshot=%s skipped_initial_notifications=%s",
            chat_id,
            chat_title,
            chat_type,
            len(current_user_ids),
            new_members_count,
            len(inactive_members),
            is_initial_snapshot,
            skipped_initial_notifications_count,
        )
    except Exception as exc:
        logger.exception("MAX polling failed for chat_id=%s title=%s type=%s: %s", chat_id, chat_title, chat_type, exc)
        insert_max_poll_run(
            chat_id=chat_id,
            chat_title=chat_title,
            members_count=None,
            status="error",
            error_text=str(exc),
        )


def run_max_members_polling_loop() -> None:
    if not MAX_STATS_POLL_ENABLED:
        logger.info("MAX polling disabled by config")
        return

    logger.info("MAX polling loop started, interval=%s sec", MAX_STATS_POLL_INTERVAL_SEC)
    while True:
        try:
            chats = fetch_chats()
            if not chats:
                insert_max_poll_run(chat_id=None, chat_title=None, members_count=0, status="empty", error_text="No chats returned")
            for chat in chats:
                process_chat(chat)
        except Exception as exc:
            logger.exception("MAX polling loop error: %s", exc)
            insert_max_poll_run(chat_id=None, chat_title=None, members_count=None, status="error", error_text=str(exc))
        time.sleep(MAX_STATS_POLL_INTERVAL_SEC)
