
# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import pytz

from config import MAX_STATS_WEBHOOK_SECRET, MAX_STATS_IGNORE_MESSAGE_CREATED
from stats_db import save_member_event

logger = logging.getLogger(__name__)
app = FastAPI(title="MAX Stats Bot")


def get_novosibirsk_now():
    tz = pytz.timezone("Asia/Novosibirsk")
    return datetime.now(tz)


def _get(data: Dict[str, Any], *path: str) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _resolve_chat_id(update: Dict[str, Any]) -> Optional[int]:
    candidates = [
        update.get("chat_id"),
        _get(update, "chat", "chat_id"),
        _get(update, "message", "recipient", "chat_id"),
        _get(update, "message", "chat_id"),
    ]
    for value in candidates:
        if value is None:
            continue
        try:
            return int(value)
        except Exception:
            continue
    return None


def _resolve_chat_title(update: Dict[str, Any]) -> str:
    return (
        _get(update, "chat", "title")
        or _get(update, "message", "recipient", "title")
        or _get(update, "message", "recipient", "name")
        or "MAX chat"
    )


def _resolve_user(update: Dict[str, Any]) -> Dict[str, Any]:
    return (
        update.get("user")
        or _get(update, "message", "sender")
        or _get(update, "sender")
        or {}
    )


def _user_name(user: Dict[str, Any]) -> str:
    return (
        user.get("name")
        or user.get("full_name")
        or "MAX user"
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/max_stats")
async def max_stats_webhook(
    request: Request,
    x_max_bot_api_secret: Optional[str] = Header(default=None, alias="X-Max-Bot-Api-Secret"),
) -> JSONResponse:
    if MAX_STATS_WEBHOOK_SECRET and MAX_STATS_WEBHOOK_SECRET != "replace_with_new_random_secret_for_max_stats_bot":
        if x_max_bot_api_secret != MAX_STATS_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="invalid webhook secret")

    update = await request.json()
    update_type = update.get("update_type", "unknown")
    logger.info("MAX stats update_type=%s payload=%s", update_type, json.dumps(update, ensure_ascii=False))

    if update_type == "message_created" and MAX_STATS_IGNORE_MESSAGE_CREATED:
        logger.info("Skipping MAX message_created update by config")
        return JSONResponse({"ok": True})

    try:
        user = _resolve_user(update)
        user_id = user.get("user_id")
        actor_name = None
        actor_id = None

        save_member_event({
            "event_dt": get_novosibirsk_now(),
            "platform": "max",
            "chat_title": _resolve_chat_title(update),
            "user_full_name": _user_name(user) if user else None,
            "user_id": int(user_id) if user_id is not None else None,
            "user_username": user.get("username") or user.get("nickname"),
            "user_phone": None,
            "action": f"max_{update_type}",
            "actor_name": actor_name,
            "actor_id": actor_id,
            "actor_username": None,
            "actor_phone": None,
            "invite_link_name": None,
            "invite_link_url": None,
            "invite_link_creator": None,
            "invite_link_is_primary": None,
            "invite_link_is_revoked": None,
            "invite_link_expires_dt": None,
            "chat_id": _resolve_chat_id(update),
            "raw_event": update,
        })
    except Exception as exc:
        logger.exception("Failed to persist MAX update: %s", exc)
        raise HTTPException(status_code=500, detail="failed to persist MAX update")

    return JSONResponse({"ok": True})
