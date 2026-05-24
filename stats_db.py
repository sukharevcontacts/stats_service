
# -*- coding: utf-8 -*-
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from logging_config import setup_logger

setup_logger()
logger = logging.getLogger(__name__)

POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://market:market@10.0.44.12:5432/marketing")
_pg_pool: Optional[SimpleConnectionPool] = None


def pg_init_pool(minconn: int = 1, maxconn: int = 5, dsn: str = POSTGRES_DSN):
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = SimpleConnectionPool(minconn, maxconn, dsn)


def pg_conn():
    if _pg_pool is None:
        pg_init_pool()
    return _pg_pool.getconn()


def pg_put_conn(conn):
    if _pg_pool is not None and conn is not None:
        _pg_pool.putconn(conn)


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def save_member_event(data: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO marketing.chanhistory_member_stat (
        event_dt, platform, chat_title, chat_type, user_full_name, user_id, user_username, user_phone,
        action, actor_name, actor_id, actor_username, actor_phone,
        invite_link_name, invite_link_url, invite_link_creator,
        invite_link_is_primary, invite_link_is_revoked, invite_link_expires_dt,
        chat_id, raw_event
    ) VALUES (
        %(event_dt)s, %(platform)s, %(chat_title)s, %(chat_type)s, %(user_full_name)s, %(user_id)s, %(user_username)s, %(user_phone)s,
        %(action)s, %(actor_name)s, %(actor_id)s, %(actor_username)s, %(actor_phone)s,
        %(invite_link_name)s, %(invite_link_url)s, %(invite_link_creator)s,
        %(invite_link_is_primary)s, %(invite_link_is_revoked)s, %(invite_link_expires_dt)s,
        %(chat_id)s, %(raw_event)s::jsonb
    )
    ON CONFLICT (event_dt, platform, user_id, chat_id, action, actor_id, invite_link_url)
    DO UPDATE SET
        chat_title             = EXCLUDED.chat_title,
        chat_type              = EXCLUDED.chat_type,
        user_full_name         = EXCLUDED.user_full_name,
        user_username          = EXCLUDED.user_username,
        user_phone             = EXCLUDED.user_phone,
        actor_name             = EXCLUDED.actor_name,
        actor_username         = EXCLUDED.actor_username,
        actor_phone            = EXCLUDED.actor_phone,
        invite_link_name       = EXCLUDED.invite_link_name,
        invite_link_creator    = EXCLUDED.invite_link_creator,
        invite_link_is_primary = EXCLUDED.invite_link_is_primary,
        invite_link_is_revoked = EXCLUDED.invite_link_is_revoked,
        invite_link_expires_dt = EXCLUDED.invite_link_expires_dt,
        raw_event              = EXCLUDED.raw_event;
    """
    params = {
        "event_dt": data.get("event_dt"),
        "platform": data.get("platform", "telegram"),
        "chat_title": data.get("chat_title"),
        "chat_type": data.get("chat_type"),
        "user_full_name": data.get("user_full_name"),
        "user_id": data.get("user_id"),
        "user_username": data.get("user_username"),
        "user_phone": data.get("user_phone"),
        "action": data.get("action"),
        "actor_name": data.get("actor_name"),
        "actor_id": data.get("actor_id"),
        "actor_username": data.get("actor_username"),
        "actor_phone": data.get("actor_phone"),
        "invite_link_name": data.get("invite_link_name"),
        "invite_link_url": data.get("invite_link_url"),
        "invite_link_creator": data.get("invite_link_creator"),
        "invite_link_is_primary": data.get("invite_link_is_primary"),
        "invite_link_is_revoked": data.get("invite_link_is_revoked"),
        "invite_link_expires_dt": data.get("invite_link_expires_dt"),
        "chat_id": data.get("chat_id"),
        "raw_event": _jsonable(data.get("raw_event")),
    }

    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("save_member_event error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def save_channel_stat(data: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO marketing.chanhistory_channels_stat (
        date, time, platform, channel_name, channel_id, users, posts, views, avg_views, comments, raw_payload
    ) VALUES (
        %(date)s, %(time)s, %(platform)s, %(channel_name)s, %(channel_id)s, %(users)s, %(posts)s, %(views)s, %(avg_views)s, %(comments)s, %(raw_payload)s::jsonb
    )
    ON CONFLICT (date, time, platform, channel_id)
    DO UPDATE SET
        channel_name = EXCLUDED.channel_name,
        users        = EXCLUDED.users,
        posts        = EXCLUDED.posts,
        views        = EXCLUDED.views,
        avg_views    = EXCLUDED.avg_views,
        comments     = EXCLUDED.comments,
        raw_payload  = EXCLUDED.raw_payload;
    """
    params = {
        "date": data.get("date"),
        "time": data.get("time"),
        "platform": data.get("platform", "telegram"),
        "channel_name": data.get("channel_name"),
        "channel_id": data.get("channel_id"),
        "users": data.get("users"),
        "posts": data.get("posts"),
        "views": data.get("views"),
        "avg_views": data.get("avg_views"),
        "comments": data.get("comments"),
        "raw_payload": _jsonable(data.get("raw_payload")),
    }

    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("save_channel_stat error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def get_telegram_chats_for_stats(chat_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Возвращает актуальный список Telegram-чатов для сбора статистики
    из marketing.chanhistory_member_stat.

    chat_kind:
      - "channel" — только Telegram-каналы: chat_type = 'channel'
      - "group"   — Telegram-группы: chat_type IN ('group', 'supergroup')
      - None      — каналы + группы

    channel_chat и none специально исключаем из статистики.
    Название чата берем из самой свежей записи по event_dt.
    """
    where_parts = [
        "platform = 'telegram'",
        "chat_id IS NOT NULL",
        "chat_title IS NOT NULL",
        "chat_type IS NOT NULL",
        "chat_type NOT IN ('channel_chat', 'none', 'private')",
    ]
    params: List[Any] = []

    if chat_kind == "channel":
        where_parts.append("chat_type = %s")
        params.append("channel")
    elif chat_kind == "group":
        where_parts.append("chat_type IN ('group', 'supergroup')")

    sql = f"""
    WITH latest AS (
        SELECT DISTINCT ON (chat_id)
            chat_id,
            chat_title,
            chat_type,
            event_dt
        FROM marketing.chanhistory_member_stat
        WHERE {" AND ".join(where_parts)}
        ORDER BY chat_id, event_dt DESC
    )
    SELECT
        chat_id,
        chat_title,
        chat_type
    FROM latest
    ORDER BY chat_type, chat_title;
    """

    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [
            {
                "chat_id": int(row[0]),
                "chat_title": row[1],
                "chat_type": row[2],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("get_telegram_chats_for_stats error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def get_active_snapshot_members(chat_id: int) -> Dict[int, Dict[str, Any]]:
    sql = """
    SELECT chat_id, chat_title, chat_type, user_id, user_username, user_full_name,
           is_admin, is_creator, member_status, first_seen_dt, last_seen_dt,
           last_poll_dt, is_active, raw_member
    FROM marketing.max_chat_members_snapshot
    WHERE chat_id = %s AND is_active = true;
    """
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (chat_id,))
            rows = cur.fetchall()
        result: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            result[int(row[3])] = {
                "chat_id": row[0],
                "chat_title": row[1],
                "chat_type": row[2],
                "user_id": row[3],
                "user_username": row[4],
                "user_full_name": row[5],
                "is_admin": row[6],
                "is_creator": row[7],
                "member_status": row[8],
                "first_seen_dt": row[9],
                "last_seen_dt": row[10],
                "last_poll_dt": row[11],
                "is_active": row[12],
                "raw_member": row[13],
            }
        return result
    except Exception as e:
        logger.error("get_active_snapshot_members error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def has_any_snapshot_for_chat(chat_id: int) -> bool:
    sql = """
    SELECT 1
    FROM marketing.max_chat_members_snapshot
    WHERE chat_id = %s
    LIMIT 1;
    """
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (chat_id,))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error("has_any_snapshot_for_chat error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def upsert_max_member_snapshot(
    *,
    chat_id: int,
    chat_title: Optional[str],
    chat_type: Optional[str],
    user_id: int,
    user_username: Optional[str],
    user_full_name: Optional[str],
    is_admin: Optional[bool],
    is_creator: Optional[bool],
    member_status: Optional[str],
    raw_member: Optional[Dict[str, Any]],
    seen_dt: Optional[datetime] = None,
) -> None:
    seen_dt = seen_dt or datetime.now()
    sql = """
    INSERT INTO marketing.max_chat_members_snapshot (
        chat_id, chat_title, chat_type, user_id, user_username, user_full_name,
        is_admin, is_creator, member_status,
        first_seen_dt, last_seen_dt, last_poll_dt, is_active, raw_member
    ) VALUES (
        %(chat_id)s, %(chat_title)s, %(chat_type)s, %(user_id)s, %(user_username)s, %(user_full_name)s,
        %(is_admin)s, %(is_creator)s, %(member_status)s,
        %(seen_dt)s, %(seen_dt)s, %(seen_dt)s, true, %(raw_member)s::jsonb
    )
    ON CONFLICT (chat_id, user_id)
    DO UPDATE SET
        chat_title = EXCLUDED.chat_title,
        chat_type = EXCLUDED.chat_type,
        user_username = EXCLUDED.user_username,
        user_full_name = EXCLUDED.user_full_name,
        is_admin = EXCLUDED.is_admin,
        is_creator = EXCLUDED.is_creator,
        member_status = EXCLUDED.member_status,
        last_seen_dt = EXCLUDED.last_seen_dt,
        last_poll_dt = EXCLUDED.last_poll_dt,
        is_active = true,
        raw_member = EXCLUDED.raw_member;
    """
    params = {
        "chat_id": chat_id,
        "chat_title": chat_title,
        "chat_type": chat_type,
        "user_id": user_id,
        "user_username": user_username,
        "user_full_name": user_full_name,
        "is_admin": is_admin,
        "is_creator": is_creator,
        "member_status": member_status,
        "seen_dt": seen_dt,
        "raw_member": _jsonable(raw_member),
    }
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("upsert_max_member_snapshot error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def mark_missing_members_inactive(chat_id: int, still_active_user_ids: list[int], poll_dt: Optional[datetime] = None) -> list[Dict[str, Any]]:
    poll_dt = poll_dt or datetime.now()
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            if still_active_user_ids:
                cur.execute(
                    """
                    SELECT user_id, user_username, user_full_name, chat_title, chat_type, raw_member
                    FROM marketing.max_chat_members_snapshot
                    WHERE chat_id = %s
                      AND is_active = true
                      AND NOT (user_id = ANY(%s));
                    """,
                    (chat_id, still_active_user_ids),
                )
            else:
                cur.execute(
                    """
                    SELECT user_id, user_username, user_full_name, chat_title, chat_type, raw_member
                    FROM marketing.max_chat_members_snapshot
                    WHERE chat_id = %s
                      AND is_active = true;
                    """,
                    (chat_id,),
                )
            rows = cur.fetchall()
            if still_active_user_ids:
                cur.execute(
                    """
                    UPDATE marketing.max_chat_members_snapshot
                    SET is_active = false,
                        last_poll_dt = %s
                    WHERE chat_id = %s
                      AND is_active = true
                      AND NOT (user_id = ANY(%s));
                    """,
                    (poll_dt, chat_id, still_active_user_ids),
                )
            else:
                cur.execute(
                    """
                    UPDATE marketing.max_chat_members_snapshot
                    SET is_active = false,
                        last_poll_dt = %s
                    WHERE chat_id = %s
                      AND is_active = true;
                    """,
                    (poll_dt, chat_id),
                )
        conn.commit()
        return [
            {
                "user_id": row[0],
                "user_username": row[1],
                "user_full_name": row[2],
                "chat_title": row[3],
                "chat_type": row[4],
                "raw_member": row[5],
            }
            for row in rows
        ]
    except Exception as e:
        conn.rollback()
        logger.error("mark_missing_members_inactive error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def get_max_chat_member_counts(chat_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Возвращает последнее количество активных участников MAX-чатов
    из marketing.max_chat_members_snapshot.

    chat_type:
      - "channel" — только каналы MAX
      - "group"   — только группы MAX
      - None      — все типы
    """
    params = []
    where_parts = ["is_active = true"]

    if chat_type:
        where_parts.append("chat_type = %s")
        params.append(chat_type)

    sql = f"""
    SELECT
        chat_id,
        COALESCE(MAX(NULLIF(chat_title, '')), 'MAX chat ' || chat_id::text) AS chat_title,
        COALESCE(MAX(NULLIF(chat_type, '')), 'unknown') AS chat_type,
        COUNT(DISTINCT user_id) AS users_count
    FROM marketing.max_chat_members_snapshot
    WHERE {" AND ".join(where_parts)}
    GROUP BY chat_id
    ORDER BY chat_type, chat_title;
    """

    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [
            {
                "chat_id": row[0],
                "chat_title": row[1],
                "chat_type": row[2],
                "users": int(row[3] or 0),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("get_max_chat_member_counts error: %s", e)
        raise
    finally:
        pg_put_conn(conn)


def insert_max_poll_run(
    *,
    chat_id: Optional[int],
    chat_title: Optional[str],
    members_count: Optional[int],
    status: str,
    error_text: Optional[str] = None,
) -> None:
    sql = """
    INSERT INTO marketing.max_chat_members_poll_run (
        poll_dt, chat_id, chat_title, members_count, status, error_text
    ) VALUES (
        now(), %(chat_id)s, %(chat_title)s, %(members_count)s, %(status)s, %(error_text)s
    );
    """
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {
                "chat_id": chat_id,
                "chat_title": chat_title,
                "members_count": members_count,
                "status": status,
                "error_text": error_text,
            })
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("insert_max_poll_run error: %s", e)
    finally:
        pg_put_conn(conn)
