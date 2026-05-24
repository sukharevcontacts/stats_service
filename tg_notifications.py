
# -*- coding: utf-8 -*-
import logging
from typing import Optional

import requests

from config import (
    TG_NOTIFY_ADMIN_IDS,
    TG_NOTIFY_BOT_TOKEN,
    TG_NOTIFY_ENABLED,
    TG_NOTIFY_PROXY_URL,
)
from logging_config import setup_logger

setup_logger()
logger = logging.getLogger(__name__)


def _telegram_url(method: str) -> str:
    return f"https://api.telegram.org/bot{TG_NOTIFY_BOT_TOKEN}/{method}"


def _proxies():
    if not TG_NOTIFY_PROXY_URL:
        return None
    return {
        "http": TG_NOTIFY_PROXY_URL,
        "https": TG_NOTIFY_PROXY_URL,
    }


def send_admin_notification(text: str, parse_mode: str = "HTML") -> None:
    if not TG_NOTIFY_ENABLED:
        return

    if not TG_NOTIFY_BOT_TOKEN:
        logger.warning("TG_NOTIFY_BOT_TOKEN is empty, skipping Telegram notification")
        return

    for admin_id in TG_NOTIFY_ADMIN_IDS:
        try:
            response = requests.post(
                _telegram_url("sendMessage"),
                data={
                    "chat_id": admin_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": "true",
                },
                proxies=_proxies(),
                timeout=30,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.error("Failed to send Telegram notification to admin_id=%s: %s", admin_id, exc)


def build_max_member_notification(
    *,
    action: str,
    chat_title: str,
    chat_id: int,
    user_id: Optional[int],
    user_username: Optional[str],
    user_full_name: Optional[str],
) -> str:
    return (
        f"<b>MAX</b>\n"
        f"Дата время: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Название группы: {chat_title or ''}\n"
        f"Имя пользователя: {user_full_name or ''}\n"
        f"ID пользователя: {user_id if user_id is not None else ''}\n"
        f"telegram_name Пользователя: {user_username or ''}\n"
        f"Телефон пользователя: \n"
        f"Действие: {action}\n"
        f"Актор: \n"
        f"ID Актора: \n"
        f"telegram_name Актора: \n"
        f"телефон Актора: \n"
        f"invite_link.name: \n"
        f"invite_link.invite_link: \n"
        f"invite_link_creator: \n"
        f"invite_link.is_primary: \n"
        f"invite_link.is_revoked: \n"
        f"invite_link.expires_date: \n"
        f"chat.id: {chat_id}"
    )


def send_max_member_notification(
    *,
    action: str,
    chat_title: str,
    chat_id: int,
    user_id: Optional[int],
    user_username: Optional[str],
    user_full_name: Optional[str],
) -> None:
    text = build_max_member_notification(
        action=action,
        chat_title=chat_title,
        chat_id=chat_id,
        user_id=user_id,
        user_username=user_username,
        user_full_name=user_full_name,
    )
    send_admin_notification(text)
