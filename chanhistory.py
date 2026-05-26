# -*- coding: utf-8 -*-
import logging
from typing import Optional, Dict, List
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    ChatMemberHandler,
    CommandHandler,
    CallbackContext,
    filters,
    MessageHandler,
)
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, date as date_cls, time as time_cls
import pytz
import datetime as dt
import matplotlib.pyplot as plt
from io import BytesIO
import pandas as pd
import re
import os
import psycopg2

from psycopg2.pool import SimpleConnectionPool
from telegram.request import HTTPXRequest

# >>> НОВОЕ: централизованное логирование
from config import TG_STATS_PROXY_URL
from logging_config import setup_logger
from stats_db import save_member_event, save_channel_stat, get_max_chat_member_counts, get_telegram_chats_for_stats

# =========================
# Logging (конкретные логгеры модулей)
# =========================
logger = logging.getLogger(__name__)


def build_ptb_request(proxy_url: Optional[str] = None) -> HTTPXRequest:
    kwargs = {
        "connect_timeout": 30.0,
        "read_timeout": 30.0,
        "write_timeout": 30.0,
    }
    if proxy_url:
        kwargs["proxy_url"] = proxy_url
    return HTTPXRequest(**kwargs)

# =========================
# Admins & state
# =========================
ADMIN_IDS = [200190627, 1389166185, 7591995723, 1001102821, 6248528837, 537341017, 1247091364]
logging_state = {admin_id: False for admin_id in ADMIN_IDS}

# =========================
# Telegram / MAX statistics split
# =========================
TELEGRAM_CHAT_TYPE_CHANNEL = "channel"
TELEGRAM_CHAT_TYPE_GROUP = "group"
TELEGRAM_CHANNEL_PLATFORM = "telegram_channel"
TELEGRAM_GROUP_PLATFORM = "telegram_group"

MAX_CHAT_TYPE_CHANNEL = "channel"
MAX_CHAT_TYPE_GROUP = "group"
MAX_CHANNEL_PLATFORM = "max_channel"
MAX_GROUP_PLATFORM = "max_group"

# =========================
# Google Sheets (only for CHANNELS list)
# =========================
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
# credentials = Credentials.from_service_account_file('/home/sukharevcontacts/telegram-bot-stats-0c69ab9aae80.json', scopes=scope)
# UPDATED: server path for credentials (Linux server)
credentials = Credentials.from_service_account_file('/var/www/chanhistory_bot/telegram-bot-stats-0c69ab9aae80.json', scopes=scope)
gc = gspread.authorize(credentials)

SPREADSHEET_ID = "1oqL1qXg1ekdzwUqe7Yddv5a2iP4C_abDWQvsjOysqZE"  # старые логи в Google (больше НЕ пишем)
CHANNELS_SHEET_ID = "1QWC62w8gpzZoA9SjDepaoqXyKQQ-w_BpigJqbGGeuw4"  # перечень каналов — оставляем в Google
STATS_SHEET_ID = "1gQDXKVAMEB5Bx9yksyKnlLtHvAJBv3QCJGjhHugHu5g"   # старая статистика в Google (больше НЕ пишем)

# =========================
# Postgres
# =========================
# БЫЛО: локальная БД coopbot
# POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://coopbot:wfrkoreh@127.0.0.1:5432/coopbot")
# СТАЛО: удалённая БД marketing (как в IDE: host localhost:5432, db marketing, user market/market)
POSTGRES_DSN = os.getenv("POSTGRES_DSN", "postgresql://market:market@10.0.44.12:5432/marketing")        
_pg_pool = None

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

# =========================
# Timezone helpers
# =========================
def get_novosibirsk_now():
    tz = pytz.timezone('Asia/Novosibirsk')
    return datetime.now(tz)

def get_novosibirsk_time_str():
    return get_novosibirsk_now().strftime('%Y-%m-%d %H:%M:%S')

# =========================
# UI (keyboard) & formatting
# =========================
def create_menu_keyboard():
    keyboard = [
        [KeyboardButton("Старт")],
        [KeyboardButton("Стоп")],
        [KeyboardButton("Поиск")],
        [KeyboardButton("Выгрузить добавления с Авито")],
        [KeyboardButton("MAX статистика")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def format_log_for_admin(log_data):
    user_link = f"<a href='tg://user?id={log_data['ID пользователя']}'>{log_data['Имя пользователя']}</a>"
    actor_link = f"<a href='tg://user?id={log_data['ID Актора']}'>{log_data['Имя актора']}</a>" if log_data.get('ID Актора') else ""
    log_message = f"""
Дата время: {log_data['Дата время']}
Название группы: {log_data['Название группы']}
Тип чата: {log_data.get('Тип чата', '')}
Пользователь: {user_link}
ID пользователя: {log_data['ID пользователя']}
telegram_name Пользователя: {log_data.get('telegram_name Пользователя', '')}
Телефон пользователя: {log_data.get('Телефон пользователя', '')}
Действие: {log_data['Действие']}
Актор: {actor_link}
ID Актора: {log_data.get('ID Актора', '')}
telegram_name Актора: {log_data.get('telegram_name Актора', '')}
телефон Актора: {log_data.get('телефон Актора', '')}
invite_link.name: {log_data.get('invite_link.name', '')}
invite_link.invite_link: {log_data.get('invite_link.invite_link', '')}
invite_link_creator: {log_data.get('invite_link_creator', '')}
invite_link.is_primary: {log_data.get('invite_link.is_primary', '')}
invite_link.is_revoked: {log_data.get('invite_link.is_revoked', '')}
invite_link.expires_date: {log_data.get('invite_link.expires_date', '')}
chat.id: {log_data['chat.id']}"""
    if log_data.get("Последнее добавление"):
        log_message += f"\n\nПоследнее добавление:\n{log_data['Последнее добавление']}"
    return log_message

# =========================
# CHANNELS list now from Postgres
# =========================
def _telegram_chats_to_monitor(chat_kind: str):
    """
    Берем Telegram-чаты для статистики из уже накопленных событий.
    Источник автообнаружения: marketing.chanhistory_member_stat.

    chat_kind:
      - "channel" — Telegram-каналы
      - "group"   — Telegram-группы / супергруппы

    Возвращаем прежний формат:
      {"name": ..., "id": ..., "region": ..., "invite_link": ..., "chat_type": ...}
    """
    try:
        rows = get_telegram_chats_for_stats(chat_kind=chat_kind)
        return [
            {
                "name": row["chat_title"],
                "id": int(row["chat_id"]),
                "region": None,
                "invite_link": None,
                "chat_type": row.get("chat_type"),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Ошибка при загрузке Telegram-чатов из member_stat: {e}")
        return []


def get_channels_to_monitor():
    """
    Telegram-каналы для статистики.
    Раньше читали из статичной marketing.mdata_channels.
    Теперь берем актуальный список из marketing.chanhistory_member_stat:
      platform = 'telegram'
      chat_type = 'channel'
    """
    return _telegram_chats_to_monitor(TELEGRAM_CHAT_TYPE_CHANNEL)


def get_groups_to_monitor():
    """
    Telegram-группы/супергруппы для статистики.
    Источник: marketing.chanhistory_member_stat:
      platform = 'telegram'
      chat_type IN ('group', 'supergroup')
    """
    return _telegram_chats_to_monitor(TELEGRAM_CHAT_TYPE_GROUP)


# =========================
# Postgres helpers for LOGS
# =========================
def pg_upsert_member_log(data: dict):
    """
    Совместимый wrapper: пишет Telegram-событие в общую таблицу через stats_db.
    SQL для marketing.chanhistory_member_stat хранится только в stats_db.py.
    """
    payload = dict(data or {})
    payload.setdefault("platform", "telegram")
    payload.setdefault("raw_event", None)
    save_member_event(payload)

def pg_find_last_join_record(user_id: int, chat_id: int) -> Optional[dict]:
    """
    Ищем последнее 'добавился'/'был добавлен' для пользователя в чате.
    Возвращаем словарь в тех же ключах, что и Google-версия использовала для форматирования.
    """
    sql = """
    SELECT event_dt, chat_title, user_full_name, user_id, user_username, action,
           actor_name, actor_id, invite_link_name, invite_link_url, chat_id
    FROM marketing.chanhistory_member_stat
    WHERE platform = 'telegram' AND user_id = %s AND chat_id = %s AND action IN ('добавился','был добавлен')
    ORDER BY event_dt DESC
    LIMIT 1;
    """
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, chat_id))
            row = cur.fetchone()
        if not row:
            return None
        event_dt, chat_title, user_full_name, user_id_v, user_username, action, actor_name, actor_id, invite_link_name, invite_link_url, chat_id_v = row
        return {
            'Дата время': event_dt.astimezone(pytz.timezone('Asia/Novosibirsk')).strftime('%Y-%m-%d %H:%M:%S') if event_dt.tzinfo else str(event_dt),
            'Название группы': chat_title,
            'Имя пользователя': user_full_name,
            'ID пользователя': user_id_v,
            'Действие': action,
            'Имя актора': actor_name,
            'ID Актора': actor_id,
            'invite_link.name': invite_link_name,
            'invite_link.invite_link': invite_link_url,
            'chat.id': chat_id_v
        }
    except Exception as e:
        logger.error(f"PG last join lookup error: {e}")
        return None
    finally:
        pg_put_conn(conn)

def pg_search_logs(query: str, limit_per_user: int = 20) -> Dict[int, Dict[str, object]]:
    """
    Поиск по БД: если query — это число -> по user_id;
    иначе ILIKE по user_full_name/ user_username.
    Возвращает dict[user_id] = {'Имя пользователя', 'ID пользователя', 'telegram_name Пользователя', 'Логи': [строки]}
    """
    conn = pg_conn()
    try:
        users: Dict[int, Dict[str, object]] = {}
        if query.isdigit():
            sql_user = """
            SELECT user_id, user_full_name, user_username
            FROM marketing.chanhistory_member_stat
            WHERE platform = 'telegram' AND user_id = %s
            GROUP BY user_id, user_full_name, user_username
            LIMIT 50;
            """
            with conn.cursor() as cur:
                cur.execute(sql_user, (int(query),))
                user_rows = cur.fetchall()
        else:
            like = f"%{query}%"
            sql_user = """
            SELECT user_id, user_full_name, user_username
            FROM marketing.chanhistory_member_stat
            WHERE platform = 'telegram' AND (user_full_name ILIKE %s OR user_username ILIKE %s)
            GROUP BY user_id, user_full_name, user_username
            LIMIT 50;
            """
            with conn.cursor() as cur:
                cur.execute(sql_user, (like, like))
                user_rows = cur.fetchall()

        for (uid, fullname, uname) in user_rows:
            users[uid] = {
                "Имя пользователя": fullname or "",
                "ID пользователя": uid,
                "telegram_name Пользователя": uname or "",
                "Логи": []
            }
            sql_logs = """
            SELECT event_dt, chat_title, action, actor_name, actor_id, actor_username,
                   actor_phone, invite_link_name, invite_link_url, invite_link_creator,
                   invite_link_is_primary, invite_link_is_revoked, invite_link_expires_dt, chat_id
            FROM marketing.chanhistory_member_stat
            WHERE platform = 'telegram' AND user_id = %s
            ORDER BY event_dt DESC
            LIMIT %s;
            """
            with conn.cursor() as cur2:
                cur2.execute(sql_logs, (uid, limit_per_user))
                for row in cur2.fetchall():
                    (event_dt, chat_title, action, actor_name, actor_id, actor_username, actor_phone,
                     invite_link_name, invite_link_url, invite_link_creator, invite_link_is_primary,
                     invite_link_is_revoked, invite_link_expires_dt, chat_id) = row
                    event_dt_str = event_dt.astimezone(pytz.timezone('Asia/Novosibirsk')).strftime('%Y-%m-%d %H:%M:%S') if event_dt and event_dt.tzinfo else str(event_dt)
                    log_entry = f"""
Дата время: {event_dt_str}
Группа: {chat_title or ''}
Пользователь: <a href='tg://user?id={uid}'>{fullname or ''}</a>
Действие: {action or ''}
Актор: <a href='tg://user?id={actor_id or ""}'>{actor_name or ""}</a>
ID Актора: {actor_id or ""}
telegram_name Актора: {actor_username or ""}
телефон Актора: {actor_phone or ""}
invite_link.name: {invite_link_name or ""}
invite_link.invite_link: {invite_link_url or ""}
invite_link_creator: {invite_link_creator or ""}
invite_link.is_primary: {invite_link_is_primary if invite_link_is_primary is not None else ""}
invite_link.is_revoked: {invite_link_is_revoked if invite_link_is_revoked is not None else ""}
invite_link.expires_date: {(invite_link_expires_dt.astimezone(pytz.timezone('Asia/Novosibirsk')).strftime('%Y-%m-%d %H:%M:%S') if (invite_link_expires_dt and invite_link_expires_dt.tzinfo) else (invite_link_expires_dt.strftime('%Y-%m-%d %H:%M:%S') if invite_link_expires_dt else ""))}
chat.id: {chat_id}
-----------------------------"""
                    users[uid]["Логи"].append(log_entry)
        return users
    except Exception as e:
        logger.error(f"PG search error: {e}")
        return {}
    finally:
        pg_put_conn(conn)

# =========================
# Postgres helpers for CHANNEL STATS
# =========================
def pg_upsert_channel_stat(date_v: dt.date, time_v: dt.time, channel_name: str, channel_id: int,
                           users: Optional[int] = None, posts: Optional[int] = None, views: Optional[int] = None,
                           avg_views: Optional[int] = None, comments: Optional[int] = None,
                           raw_payload=None, platform: str = TELEGRAM_CHANNEL_PLATFORM):
    """
    Совместимый wrapper: пишет статистику канала/чата через stats_db.
    SQL для marketing.chanhistory_channels_stat хранится только в stats_db.py.

    platform:
      - telegram_channel — Telegram-каналы
      - telegram_group   — Telegram-группы / супергруппы
      - max_channel      — каналы MAX
      - max_group        — группы MAX
    """
    save_channel_stat({
        "date": date_v,
        "time": time_v,
        "platform": platform,
        "channel_name": channel_name,
        "channel_id": channel_id,
        "users": users,
        "posts": posts,
        "views": views,
        "avg_views": avg_views,
        "comments": comments,
        "raw_payload": raw_payload,
    })

def pg_stats_last_days(days: int = 30, platform: Optional[str] = TELEGRAM_CHANNEL_PLATFORM) -> pd.DataFrame:
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            if platform:
                cur.execute(
                    """
                    SELECT date, time, channel_name, channel_id, users, posts, views, avg_views, comments
                    FROM marketing.chanhistory_channels_stat
                    WHERE date >= CURRENT_DATE - INTERVAL %s
                      AND platform = %s
                    ORDER BY date, time;
                    """,
                    (f"{days} days", platform)
                )
            else:
                cur.execute(
                    """
                    SELECT date, time, channel_name, channel_id, users, posts, views, avg_views, comments
                    FROM marketing.chanhistory_channels_stat
                    WHERE date >= CURRENT_DATE - INTERVAL %s
                    ORDER BY date, time;
                    """,
                    (f"{days} days",)
                )
            rows = cur.fetchall()
            cols = ["DATE", "TIME", "NAME", "CHANNEL_ID", "USERS", "POSTS", "VIEWS", "AVG_VIEWS", "COMMENTS"]
            df = pd.DataFrame(rows, columns=cols)
            if not df.empty:
                df["DATE"] = pd.to_datetime(df["DATE"])
            return df
    except Exception as e:
        logger.error(f"PG fetch stats error: {e}")
        return pd.DataFrame(columns=["DATE","TIME","NAME","CHANNEL_ID","USERS","POSTS","VIEWS","AVG_VIEWS","COMMENTS"])
    finally:
        pg_put_conn(conn)

def pg_any_stats_for_date(date_iso: str, platform: Optional[str] = TELEGRAM_CHANNEL_PLATFORM) -> bool:
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            if platform:
                cur.execute(
                    "SELECT 1 FROM marketing.chanhistory_channels_stat WHERE date = %s AND platform = %s LIMIT 1;",
                    (date_iso, platform)
                )
            else:
                cur.execute("SELECT 1 FROM marketing.chanhistory_channels_stat WHERE date = %s LIMIT 1;", (date_iso,))
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"PG check stats for date error: {e}")
        return False
    finally:
        pg_put_conn(conn)

# =========================
# AVITO USERS EXPORT (NEW)
# =========================
def pg_fetch_avito_users_df() -> pd.DataFrame:
    """
    Читает содержимое вьюшки marketing.v_chanhistory_user_avito в DataFrame.
    """
    conn = pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM marketing.v_chanhistory_user_avito;")
            rows = cur.fetchall()
            colnames = [desc[0] for desc in cur.description]
        df = pd.DataFrame(rows, columns=colnames)
        return df
    except Exception as e:
        logger.error(f"PG fetch avito users error: {e}")
        return pd.DataFrame()
    finally:
        pg_put_conn(conn)

def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "users_avito") -> BytesIO:
    """
    Преобразует DataFrame в Excel (XLSX) и возвращает BytesIO.
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    output.seek(0)
    return output

async def users_avito_command(update: Update, context: CallbackContext):
    """
    Команда /users_avito — выгружает в Excel вьюшку marketing.v_chanhistory_user_avito и отправляет файл.
    Доступна только администраторам.
    """
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.", reply_markup=create_menu_keyboard())
        return
    try:
        df = pg_fetch_avito_users_df()
        if df.empty:
            await update.message.reply_text("Вьюшка пуста или недоступна.", reply_markup=create_menu_keyboard())
            return
        excel_io = df_to_excel_bytes(df, sheet_name="users_avito")
        now_str = get_novosibirsk_now().strftime("%Y%m%d_%H%M%S")
        filename = f"users_avito_{now_str}.xlsx"
        await update.message.reply_document(document=excel_io, filename=filename, caption="Выгрузка добавлений с Авито", reply_markup=create_menu_keyboard())
    except Exception as e:
        logger.error(f"Ошибка при выгрузке users_avito: {e}")
        await update.message.reply_text("Ошибка при формировании выгрузки.", reply_markup=create_menu_keyboard())

# =========================
# Telegram bot logic
# =========================
async def get_chat_list(bot: Bot):
    chat_list = []
    try:
        updates = await bot.get_updates(offset=-1, limit=100)
        for update in updates:
            if update.message and update.message.chat.type in ["group", "supergroup", "channel"]:
                chat_list.append(update.message.chat.id)
    except Exception as e:
        logger.error(f"Ошибка при получении списка чатов: {e}")
    return list(set(chat_list))

async def fetch_and_record_history(context: CallbackContext):
    bot = context.bot if hasattr(context, "bot") else context
    chat_ids = await get_chat_list(bot)
    if not chat_ids:
        logger.info("Бот не состоит ни в каких чатах.")
        return
    for chat_id in chat_ids:
        try:
            chat = await bot.get_chat(chat_id)
            chat_title = chat.title or "Чат без названия"
            admins = await bot.get_chat_administrators(chat_id)
            for admin in admins:
                user = admin.user
                user_full_name = f"{user.first_name} {user.last_name or ''}".strip()
                user_username = user.username or "Нет username"
                data = {
                    "event_dt": get_novosibirsk_now(),
                    "chat_title": chat_title,
                    "chat_type": getattr(chat, "type", None),
                    "user_full_name": user_full_name,
                    "user_id": user.id,
                    "user_username": user_username,
                    "user_phone": None,
                    "action": "является участником",
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
                    "chat_id": chat.id,
                    "platform": "telegram",
                    "raw_event": None
                }
                pg_upsert_member_log(data)
                logger.info(f"Записана история (PG) для чата {chat_title} и пользователя {user_full_name}.")
        except Exception as e:
            logger.error(f"Ошибка при получении истории для чата {chat_id}: {e}")

async def track_chat_members(update: Update, context: CallbackContext):
    chat = update.effective_chat
    user = update.chat_member.new_chat_member.user
    actor = update.chat_member.from_user if update.chat_member.from_user else None
    status = update.chat_member.new_chat_member.status

    action = ""
    actor_name = None
    actor_id = None
    actor_username = None

    if status == "left":
        action = "удалился"
    elif status == "kicked":
        action = "был исключен"
        if actor:
            actor_name = f"{actor.first_name} {actor.last_name or ''}".strip()
            actor_id = actor.id
            actor_username = actor.username or "Нет username"
    elif status == "member":
        action = "добавился"
        if actor and actor.id != user.id:
            action = "был добавлен"
            actor_name = f"{actor.first_name} {actor.last_name or ''}".strip()
            actor_id = actor.id
            actor_username = actor.username or "Нет username"

    if not actor or actor.id == user.id:
        actor_name = None
        actor_id = None
        actor_username = None

    chat_title = chat.title if chat.title else "Чат без названия"
    user_full_name = f"{user.first_name} {user.last_name or ''}".strip()
    user_username = user.username or "Нет username"
    user_phone = getattr(user, "phone_number", None)
    actor_phone = getattr(actor, "phone_number", None) if actor else None

    invite_link = update.chat_member.invite_link
    invite_link_url = None
    invite_link_name = None
    invite_link_creator = None
    invite_link_is_primary = None
    invite_link_is_revoked = None
    invite_link_expires_dt = None

    if invite_link:
        invite_link_url = invite_link.invite_link
        if invite_link_url and "..." in invite_link_url:
            try:
                chat_id = update.effective_chat.id
                full_invite_link = await context.bot.export_chat_invite_link(chat_id)
                invite_link_url = full_invite_link or invite_link_url
            except Exception as e:
                logger.warning(f"Не удалось экспортировать полную ссылку для чата {chat.id}: {e}")
        invite_link_name = getattr(invite_link, "name", None)
        invite_link_creator = invite_link.creator.id if getattr(invite_link, "creator", None) else None
        invite_link_is_primary = bool(getattr(invite_link, "is_primary", False))
        invite_link_is_revoked = bool(getattr(invite_link, "is_revoked", False))
        invite_link_expires_dt = invite_link.expire_date

    event_dt = get_novosibirsk_now()

    data = {
        "event_dt": event_dt,
        "chat_title": chat_title,
        "chat_type": getattr(chat, "type", None),
        "user_full_name": user_full_name,
        "user_id": user.id,
        "user_username": user_username,
        "user_phone": user_phone,
        "action": action,
        "actor_name": actor_name,
        "actor_id": actor_id,
        "actor_username": actor_username,
        "actor_phone": actor_phone,
        "invite_link_name": invite_link_name,
        "invite_link_url": invite_link_url,
        "invite_link_creator": invite_link_creator,
        "invite_link_is_primary": invite_link_is_primary,
        "invite_link_is_revoked": invite_link_is_revoked,
        "invite_link_expires_dt": invite_link_expires_dt,
        "chat_id": chat.id,
        "platform": "telegram",
        "raw_event": update.to_dict() if hasattr(update, "to_dict") else None
    }


    # Детальный лог в консоль/файл — теперь через централизованный конфиг
    event_dt_str = event_dt.strftime('%Y-%m-%d %H:%M:%S')
    logger.info(
        "Дата время: %s | Название группы: %s | Имя пользователя: %s | ID пользователя: %s | "
        "telegram_name Пользователя: %s | Телефон пользователя: %s | Действие: %s | "
        "Имя актора: %s | ID Актора: %s | telegram_name Актора: %s | телефон Актора: %s | "
        "invite_link.name: %s | invite_link.invite_link: %s | invite_link_creator: %s | "
        "invite_link.is_primary: %s | invite_link.is_revoked: %s | invite_link.expires_date: %s | chat.id: %s",
        event_dt_str, chat_title, user_full_name, user.id, user_username, user_phone or "",
        action, actor_name or "", actor_id or "", actor_username or "", actor_phone or "",
        invite_link_name or "", invite_link_url or "", invite_link_creator or "",
        str(invite_link_is_primary) if invite_link_is_primary is not None else "",
        str(invite_link_is_revoked) if invite_link_is_revoked is not None else "",
        invite_link_expires_dt.strftime('%Y-%m-%d %H:%M:%S') if invite_link_expires_dt else "", chat.id
    )
    try:
        pg_upsert_member_log(data)
        logger.info("Запись успешно добавлена в Postgres.")
    except Exception as e:
        logger.error(f"Ошибка записи в Postgres: {e}")

    admin_log_data = {
        "Дата время": event_dt.strftime('%Y-%m-%d %H:%M:%S'),
        "Название группы": chat_title,
        "Тип чата": getattr(chat, "type", None) or "",
        "Имя пользователя": user_full_name,
        "ID пользователя": user.id,
        "telegram_name Пользователя": user_username,
        "Телефон пользователя": user_phone or "",
        "Действие": action,
        "Имя актора": actor_name or "",
        "ID Актора": actor_id or "",
        "telegram_name Актора": actor_username or "",
        "телефон Актора": actor_phone or "",
        "invite_link.name": invite_link_name or "",
        "invite_link.invite_link": invite_link_url or "",
        "invite_link_creator": invite_link_creator or "",
        "invite_link.is_primary": str(invite_link_is_primary) if invite_link_is_primary is not None else "",
        "invite_link.is_revoked": str(invite_link_is_revoked) if invite_link_is_revoked is not None else "",
        "invite_link.expires_date": invite_link_expires_dt.strftime('%Y-%m-%d %H:%M:%S') if invite_link_expires_dt else "",
        "chat.id": chat.id
    }

    if action == "удалился":
        logger.info(f"Пользователь с ID {user.id} удалился из чата {chat.id}. Ищем последнее добавление...")
        logger.info(f"Начинаем поиск последнего добавления пользователя с ID {user.id} в чате {chat.id}.")
        last_join_record = pg_find_last_join_record(user.id, chat.id)
        if last_join_record:
            admin_log_data["Последнее добавление"] = f"""
Дата время: {last_join_record.get('Дата время')}
Название группы: {last_join_record.get('Название группы')}
Пользователь: {last_join_record.get('Имя пользователя')}
ID пользователя: {last_join_record.get('ID пользователя')}
Действие: {last_join_record.get('Действие')}
Актор: {last_join_record.get('Имя актора')}
ID Актора: {last_join_record.get('ID Актора')}
invite_link.name: {last_join_record.get('invite_link.name')}
invite_link.invite_link: {last_join_record.get('invite_link.invite_link')}
chat.id: {last_join_record.get('chat.id')}"""
            logger.info(f"Найдена запись о последнем добавлении пользователя с ID {user.id} в чате {chat.id}.")
            logger.info(f"Информация о последнем добавлении пользователя с ID {user.id} найдена и добавлена в лог.")
        else:
            admin_log_data["Последнее добавление"] = "Информация о последнем добавлении не найдена в БД."
            logger.info(f"Информация о последнем добавлении пользователя с ID {user.id} не найдена.")

    for admin_id, is_logging_enabled in logging_state.items():
        if is_logging_enabled:
            try:
                formatted_log = format_log_for_admin(admin_log_data)
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"{formatted_log}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить лог администратору {admin_id}: {e}")

# =========================
# Commands & Handlers
# =========================
async def start_logging(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        if not logging_state[user_id]:
            logging_state[user_id] = True
            await update.message.reply_text("Логирование началось. Вы будете получать логи.", reply_markup=create_menu_keyboard())
        else:
            await update.message.reply_text("Логирование уже включено.", reply_markup=create_menu_keyboard())
    else:
        await update.message.reply_text("У вас нет прав администратора.")

async def stop_logging(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        logging_state[user_id] = False
        await update.message.reply_text("Логирование остановлено. Вы больше не будете получать логи.", reply_markup=create_menu_keyboard())
    else:
        await update.message.reply_text("У вас нет прав администратора.")

async def handle_search_menu(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return
    await update.message.reply_text("Введите параметр для поиска (ID, имя, username или часть текста):", reply_markup=None)
    context.user_data["awaiting_search_query"] = True

async def handle_message(update: Update, context: CallbackContext):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    low = text.lower()
    user_id = update.message.from_user.id if update.message.from_user else None

    if low == "старт":
        await start_logging(update, context)
        return
    if low == "стоп":
        await stop_logging(update, context)
        return
    if low == "поиск":
        await handle_search_menu(update, context)
        return
    if low == "выгрузить добавления с авито":
        await users_avito_command(update, context)
        return
    if low == "max статистика":
        await max_stats_command(update, context)
        return

    if context.user_data.get("awaiting_search_query"):
        query = text.strip()
        if not query:
            await update.message.reply_text("Пожалуйста, укажите параметр для поиска.", reply_markup=create_menu_keyboard())
            return
        try:
            found_users = pg_search_logs(query, limit_per_user=20)
            if not found_users:
                await update.message.reply_text("Пользователи не найдены.", reply_markup=create_menu_keyboard())
                context.user_data.pop("awaiting_search_query", None)
                return

            for user_id_record, user_data in found_users.items():
                user_link = f"<a href='tg://user?id={user_id_record}'>{user_data['Имя пользователя']}</a>"
                header_message = (
                    f"Имя пользователя: {user_link}\n"
                    f"ID пользователя: {user_data['ID пользователя']}\n"
                    f"telegram_name Пользователя: {user_data['telegram_name Пользователя']}\n"
                    "Логи:\n"
                )
                await update.message.reply_text(header_message, parse_mode="HTML")
                for log_entry in user_data["Логи"]:
                    await update.message.reply_text(log_entry, parse_mode="HTML")

            await update.message.reply_text("Поиск завершен.", reply_markup=create_menu_keyboard())
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователя (PG): {e}")
            await update.message.reply_text("Произошла ошибка при выполнении запроса.", reply_markup=create_menu_keyboard())
        finally:
            context.user_data.pop("awaiting_search_query", None)

# =========================
# Statistics (use Postgres)
# =========================
async def auto_stats_job(context: CallbackContext):
    try:
        df_channels = pg_stats_last_days(30, platform=TELEGRAM_CHANNEL_PLATFORM)
        df_groups = pg_stats_last_days(30, platform=TELEGRAM_GROUP_PLATFORM)

        for admin_id in ADMIN_IDS:
            await send_stats_graphs_pack(
                bot=context.bot,
                chat_id=admin_id,
                df=df_channels,
                title_prefix="Telegram каналы",
                item_caption_prefix="Авто-статистика Telegram-канала",
                summary_caption="📊 Telegram каналы: сводная статистика",
                total_caption="📊 Telegram каналы: суммарное количество подписчиков",
                total_label="Всего подписчиков Telegram-каналов",
            )
            await send_stats_graphs_pack(
                bot=context.bot,
                chat_id=admin_id,
                df=df_groups,
                title_prefix="Telegram группы",
                item_caption_prefix="Авто-статистика Telegram-группы",
                summary_caption="📊 Telegram группы: сводная статистика",
                total_caption="📊 Telegram группы: суммарное количество участников",
                total_label="Всего участников Telegram-групп",
            )

    except Exception as e:
        logger.error(f"Ошибка в авто-статистике Telegram (PG): {e}")
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, "⚠ Ошибка при формировании Telegram авто-отчета (БД)")


async def stats_command(update: Update, context: CallbackContext):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        df_channels = pg_stats_last_days(30, platform=TELEGRAM_CHANNEL_PLATFORM)
        df_groups = pg_stats_last_days(30, platform=TELEGRAM_GROUP_PLATFORM)

        await send_stats_graphs_pack(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            df=df_channels,
            title_prefix="Telegram каналы",
            item_caption_prefix="Статистика Telegram-канала",
            summary_caption="📊 Telegram каналы: сводная статистика",
            total_caption="📊 Telegram каналы: суммарное количество подписчиков",
            total_label="Всего подписчиков Telegram-каналов",
        )
        await send_stats_graphs_pack(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            df=df_groups,
            title_prefix="Telegram группы",
            item_caption_prefix="Статистика Telegram-группы",
            summary_caption="📊 Telegram группы: сводная статистика",
            total_caption="📊 Telegram группы: суммарное количество участников",
            total_label="Всего участников Telegram-групп",
        )

    except Exception as e:
        logger.error(f"Ошибка в /stats Telegram (БД): {e}")
        await update.message.reply_text("Произошла ошибка при построении Telegram-графиков (БД).")


# =========================
# Shared statistics graphs for Telegram and MAX
# =========================
async def send_stats_graphs_pack(bot: Bot, chat_id: int, df: pd.DataFrame, title_prefix: str,
                                 item_caption_prefix: str, summary_caption: str, total_caption: str,
                                 total_label: str = "Всего участников"):
    """
    Рисует пакет графиков по той же логике, что и старая Telegram-статистика:
      1. отдельно каждый канал/группа
      2. сводный график со всеми линиями
      3. суммарный график по всем каналам/группам
    """
    if df.empty:
        await bot.send_message(chat_id, f"Нет данных за последние 30 дней: {title_prefix}.")
        return

    channels = df['NAME'].unique()

    for channel in channels:
        plt.figure()
        channel_data = df[df['NAME'] == channel]
        plt.plot(channel_data['DATE'], channel_data['USERS'], marker='o')
        plt.title(f"{title_prefix}: {channel}")
        plt.xlabel("Дата")
        plt.ylabel("Участники")
        plt.xticks(rotation=45)
        plt.grid(True)

        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        plt.close()

        await bot.send_photo(chat_id=chat_id, photo=buf, caption=f"{item_caption_prefix}: {channel}")

    plt.figure()
    for channel in channels:
        channel_data = df[df['NAME'] == channel]
        plt.plot(channel_data['DATE'], channel_data['USERS'], marker='o', label=channel)

    plt.title(f"Сводная статистика: {title_prefix}")
    plt.xlabel("Дата")
    plt.ylabel("Участники")
    plt.xticks(rotation=45)
    plt.legend()
    plt.grid(True)

    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close()

    await bot.send_photo(chat_id=chat_id, photo=buf, caption=summary_caption)

    plt.figure()
    sum_users = df.groupby('DATE')['USERS'].sum()
    plt.plot(sum_users.index, sum_users.values, marker='o', label=total_label)
    plt.title(f"Суммарная статистика: {title_prefix}")
    plt.xlabel("Дата")
    plt.ylabel("Участники")
    plt.xticks(rotation=45)
    plt.grid(True)
    plt.legend()

    buf_sum = BytesIO()
    plt.savefig(buf_sum, format='png', bbox_inches='tight')
    buf_sum.seek(0)
    plt.close()

    await bot.send_photo(chat_id=chat_id, photo=buf_sum, caption=total_caption)


async def auto_max_stats_job(context: CallbackContext):
    """
    Авто-отчет по MAX в Telegram-бота.
    Отдельно отправляет:
      - MAX-каналы
      - MAX-группы
    """
    try:
        df_channels = pg_stats_last_days(30, platform=MAX_CHANNEL_PLATFORM)
        df_groups = pg_stats_last_days(30, platform=MAX_GROUP_PLATFORM)

        for admin_id in ADMIN_IDS:
            await send_stats_graphs_pack(
                bot=context.bot,
                chat_id=admin_id,
                df=df_channels,
                title_prefix="MAX каналы",
                item_caption_prefix="Авто-статистика MAX-канала",
                summary_caption="📊 MAX каналы: сводная статистика",
                total_caption="📊 MAX каналы: суммарное количество участников",
                total_label="Всего участников MAX-каналов",
            )
            await send_stats_graphs_pack(
                bot=context.bot,
                chat_id=admin_id,
                df=df_groups,
                title_prefix="MAX группы",
                item_caption_prefix="Авто-статистика MAX-группы",
                summary_caption="📊 MAX группы: сводная статистика",
                total_caption="📊 MAX группы: суммарное количество участников",
                total_label="Всего участников MAX-групп",
            )
    except Exception as e:
        logger.error(f"Ошибка в авто-статистике MAX: {e}")
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, "⚠ Ошибка при формировании MAX авто-отчета")


async def max_stats_command(update: Update, context: CallbackContext):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав администратора.")
        return

    try:
        df_channels = pg_stats_last_days(30, platform=MAX_CHANNEL_PLATFORM)
        df_groups = pg_stats_last_days(30, platform=MAX_GROUP_PLATFORM)

        await send_stats_graphs_pack(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            df=df_channels,
            title_prefix="MAX каналы",
            item_caption_prefix="Статистика MAX-канала",
            summary_caption="📊 MAX каналы: сводная статистика",
            total_caption="📊 MAX каналы: суммарное количество участников",
            total_label="Всего участников MAX-каналов",
        )
        await send_stats_graphs_pack(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            df=df_groups,
            title_prefix="MAX группы",
            item_caption_prefix="Статистика MAX-группы",
            summary_caption="📊 MAX группы: сводная статистика",
            total_caption="📊 MAX группы: суммарное количество участников",
            total_label="Всего участников MAX-групп",
        )
    except Exception as e:
        logger.error(f"Ошибка в /maxstats: {e}")
        await update.message.reply_text("Произошла ошибка при построении MAX-графиков.")


# =========================
# Daily stats collection writes to Postgres
# =========================
async def get_channel_stats(bot: Bot, channel_id: int):
    try:
        chat = await bot.get_chat(channel_id)
        members_count = await bot.get_chat_member_count(channel_id)
        posts_yesterday = 5
        views_yesterday = 1000
        comments_yesterday = 50
        return {
            "users": members_count,
            "posts": posts_yesterday,
            "views": views_yesterday,
            "avg_views": views_yesterday // posts_yesterday if posts_yesterday else 0,
            "comments": comments_yesterday,
        }
    except Exception as e:
        logger.error(f"Ошибка при сборе статистики канала {channel_id}: {e}")
        return None

def telegram_platform_by_chat_kind(chat_kind: str) -> str:
    return TELEGRAM_CHANNEL_PLATFORM if chat_kind == TELEGRAM_CHAT_TYPE_CHANNEL else TELEGRAM_GROUP_PLATFORM


def telegram_title_by_chat_kind(chat_kind: str) -> str:
    return "Telegram-канала" if chat_kind == TELEGRAM_CHAT_TYPE_CHANNEL else "Telegram-группы"


async def write_stats_to_pg(
    context: CallbackContext,
    channel_name,
    channel_id,
    stats,
    platform: str = TELEGRAM_CHANNEL_PLATFORM,
    entity_title: str = "Telegram-канала",
):
    try:
        nsk_now = get_novosibirsk_now()
        date_v = nsk_now.date()
        time_v = nsk_now.time().replace(second=0, microsecond=0)
        pg_upsert_channel_stat(
            date_v=date_v,
            time_v=time_v,
            channel_name=channel_name,
            channel_id=channel_id,
            users=stats["users"],
            posts=stats["posts"],
            views=stats["views"],
            avg_views=stats["avg_views"],
            comments=stats["comments"],
            raw_payload={
                "source": "telegram_get_chat_member_count",
                "platform": platform,
            },
            platform=platform,
        )
        logger.info(f"[PG] Статистика для {channel_name} записана: platform={platform}.")
        stats_message = f"""
📊 [Статистика {entity_title}] Добавлена запись в {time_v.strftime('%H:%M')}
Название: {channel_name} (ID: {channel_id})
Показатели:
├ Участники/подписчики: {stats["users"]}
├ Посты за вчера: {stats["posts"]}
├ Просмотры: {stats["views"]}
├ Ср. просмотры: {stats["avg_views"]}
└ Комментарии: {stats["comments"]}
Сохранено в БД (chanhistory_channels_stat), platform={platform}"""
        for admin_id, is_logging_enabled in logging_state.items():
            if is_logging_enabled:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=stats_message
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить статистику админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка записи статистики в БД: {e}")


async def daily_stats_update(context: CallbackContext, chat_kinds: Optional[List[str]] = None):
    bot = context.bot
    selected_chat_kinds = chat_kinds or [TELEGRAM_CHAT_TYPE_CHANNEL, TELEGRAM_CHAT_TYPE_GROUP]

    if TELEGRAM_CHAT_TYPE_CHANNEL in selected_chat_kinds:
        channels = get_channels_to_monitor()
        for channel in channels:
            stats = await get_channel_stats(bot, channel["id"])
            if stats:
                await write_stats_to_pg(
                    context,
                    channel["name"],
                    channel["id"],
                    stats,
                    platform=TELEGRAM_CHANNEL_PLATFORM,
                    entity_title=telegram_title_by_chat_kind(TELEGRAM_CHAT_TYPE_CHANNEL),
                )

    if TELEGRAM_CHAT_TYPE_GROUP in selected_chat_kinds:
        groups = get_groups_to_monitor()
        for group in groups:
            stats = await get_channel_stats(bot, group["id"])
            if stats:
                await write_stats_to_pg(
                    context,
                    group["name"],
                    group["id"],
                    stats,
                    platform=TELEGRAM_GROUP_PLATFORM,
                    entity_title=telegram_title_by_chat_kind(TELEGRAM_CHAT_TYPE_GROUP),
                )


def max_platform_by_chat_type(chat_type: str) -> str:
    return MAX_CHANNEL_PLATFORM if chat_type == MAX_CHAT_TYPE_CHANNEL else MAX_GROUP_PLATFORM


def max_title_by_chat_type(chat_type: str) -> str:
    return "MAX-канал" if chat_type == MAX_CHAT_TYPE_CHANNEL else "MAX-группа"


async def write_max_stats_to_pg(context: CallbackContext, chat_type: str, chat_name: str, chat_id: int, users: int):
    try:
        nsk_now = get_novosibirsk_now()
        date_v = nsk_now.date()
        time_v = nsk_now.time().replace(second=0, microsecond=0)
        platform = max_platform_by_chat_type(chat_type)
        entity_title = max_title_by_chat_type(chat_type)

        pg_upsert_channel_stat(
            date_v=date_v,
            time_v=time_v,
            channel_name=chat_name,
            channel_id=chat_id,
            users=users,
            posts=0,
            views=0,
            avg_views=0,
            comments=0,
            raw_payload={
                "source": "max_chat_members_snapshot",
                "chat_type": chat_type,
            },
            platform=platform,
        )

        logger.info(f"[PG] MAX статистика для {chat_name} записана: type={chat_type}, users={users}.")
        stats_message = f"""
📊 [Статистика {entity_title}] Добавлена запись в {time_v.strftime('%H:%M')}
Название: {chat_name} (ID: {chat_id})
Показатели:
└ Участники: {users}
Сохранено в БД (chanhistory_channels_stat), platform={platform}"""

        for admin_id, is_logging_enabled in logging_state.items():
            if is_logging_enabled:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=stats_message
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить MAX статистику админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка записи MAX статистики в БД: {e}")


async def daily_max_stats_update(context: CallbackContext, chat_types: Optional[List[str]] = None):
    selected_chat_types = chat_types or [MAX_CHAT_TYPE_CHANNEL, MAX_CHAT_TYPE_GROUP]

    for chat_type in selected_chat_types:
        try:
            chats = get_max_chat_member_counts(chat_type=chat_type)
        except Exception as e:
            logger.error(f"Ошибка при загрузке MAX статистики из snapshot для chat_type={chat_type}: {e}")
            continue

        if not chats:
            logger.info(f"Нет MAX чатов для статистики chat_type={chat_type}")
            continue

        for chat in chats:
            await write_max_stats_to_pg(
                context=context,
                chat_type=chat_type,
                chat_name=chat["chat_title"],
                chat_id=int(chat["chat_id"]),
                users=int(chat["users"]),
            )


async def check_missed_stats(application: Application):
    nsk_now = get_novosibirsk_now()
    today_date = nsk_now.strftime('%Y-%m-%d')

    missed_telegram_chat_kinds: List[str] = []
    if not pg_any_stats_for_date(today_date, platform=TELEGRAM_CHANNEL_PLATFORM):
        missed_telegram_chat_kinds.append(TELEGRAM_CHAT_TYPE_CHANNEL)
    if not pg_any_stats_for_date(today_date, platform=TELEGRAM_GROUP_PLATFORM):
        missed_telegram_chat_kinds.append(TELEGRAM_CHAT_TYPE_GROUP)

    if missed_telegram_chat_kinds:
        await daily_stats_update(application, chat_kinds=missed_telegram_chat_kinds)

    missed_max_chat_types: List[str] = []
    if not pg_any_stats_for_date(today_date, platform=MAX_CHANNEL_PLATFORM):
        missed_max_chat_types.append(MAX_CHAT_TYPE_CHANNEL)
    if not pg_any_stats_for_date(today_date, platform=MAX_GROUP_PLATFORM):
        missed_max_chat_types.append(MAX_CHAT_TYPE_GROUP)

    if missed_max_chat_types:
        await daily_max_stats_update(application, chat_types=missed_max_chat_types)

# =========================
# Post init hook
# =========================
async def on_start(application: Application):
    for admin_id in ADMIN_IDS:
        logging_state[admin_id] = True
        logger.info(f"Автоматически включено логирование для админа {admin_id}")
    await fetch_and_record_history(application)
    await check_missed_stats(application)

# =========================
# postview (каналы из Google, контент постов через Telegram API)
# =========================
async def get_channel_posts_stats(bot: Bot, channel_id: int):
    try:
        posts = []
        # Этот метод в PTB может отличаться; оставлено как заглушка.
        # Замените на свой способ получения постов канала.
        return posts
    except Exception as e:
        logger.error(f"Ошибка при получении постов: {e}")
        return []

async def postview_command(update: Update, context: CallbackContext):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    try:
        bot = context.bot
        channels = get_channels_to_monitor()

        if not channels:
            await update.message.reply_text("📭 Нет каналов для мониторинга. Проверьте записи в marketing.chanhistory_member_stat с chat_type=channel.")
            return

        for channel in channels:
            try:
                posts_stats = await get_channel_posts_stats(bot, channel["id"])
                if not posts_stats:
                    await update.message.reply_text(
                        f"📭 В канале {channel['name']} не найдено подходящих постов.\n"
                        f"Проверьте последние сообщения."
                    )
                    continue

                report = []
                report.append(f"📊 <b>Канал: {channel['name']}</b>")
                report.append(f"🔗 ID: {channel['id']}")

                if channel.get('region'):
                    report.append(f"📍 Регион: {channel['region']}")

                report.append("\n<b>Статистика постов:</b>")

                for post in posts_stats:
                    post_info = (
                        f"{post.get('hashtag','')} — {post.get('views','N/A')} просмотров\n"
                        f"<i>{post.get('preview','')}</i>"
                    )
                    report.append(post_info)

                message_text = "\n\n".join(report)
                max_length = 4000

                if len(message_text) > max_length:
                    parts = [message_text[i:i+max_length] for i in range(0, len(message_text), max_length)]
                    for part in parts:
                        await update.message.reply_text(part, parse_mode="HTML")
                else:
                    await update.message.reply_text(message_text, parse_mode="HTML")

            except Exception as channel_error:
                logger.error(f"Ошибка обработки канала {channel['name']}: {channel_error}")
                await update.message.reply_text(
                    f"⚠ Ошибка при обработке канала {channel['name']}.\n"
                    f"Подробности в логах."
                )

    except Exception as main_error:
        logger.error(f"Критическая ошибка в postview_command: {main_error}")
        await update.message.reply_text(
            "⚠ Произошла критическая ошибка при формировании отчета.\n"
            "Проверьте логи бота."
        )

# =========================
# Main
# =========================
async def on_error(update: object, context: CallbackContext) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def run_telegram_bot():
    # >>> НОВОЕ: инициализируем логирование РАНЬШЕ всего
    # Можно управлять окружением: LOG_FILE, LOG_LEVEL, LOG_TO_CONSOLE и т.д.
    setup_logger()

    pg_init_pool(dsn=POSTGRES_DSN)

    # Лучше подтягивать токен из окружения, но для совместимости оставим как было
    token = os.getenv("BOT_TOKEN", "7612731502:AAEs0DlxR15VlZKbn0X9W8oSpH8niUQXSXQ")

    request = build_ptb_request(TG_STATS_PROXY_URL)
    get_updates_request = build_ptb_request(TG_STATS_PROXY_URL)

    application = (
        Application.builder()
        .token(token)
        .request(request)
        .get_updates_request(get_updates_request)
        .build()
    )
    application.add_error_handler(on_error)

    application.add_handler(ChatMemberHandler(track_chat_members, chat_member_types=ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(CommandHandler("start", start_logging, filters=filters.User(ADMIN_IDS)))
    application.add_handler(CommandHandler("stop", stop_logging, filters=filters.User(ADMIN_IDS)))
    application.add_handler(CommandHandler("stats", stats_command, filters=filters.User(ADMIN_IDS)))
    application.add_handler(CommandHandler("maxstats", max_stats_command, filters=filters.User(ADMIN_IDS)))
    application.add_handler(CommandHandler("postview", postview_command, filters=filters.User(ADMIN_IDS)))
    # NEW: /users_avito
    application.add_handler(CommandHandler("users_avito", users_avito_command, filters=filters.User(ADMIN_IDS)))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.job_queue.run_daily(
        auto_stats_job,
        time=dt.time(hour=9, minute=30, tzinfo=pytz.timezone('Asia/Novosibirsk')),
        name="auto_stats"
    )
    application.job_queue.run_daily(
        daily_stats_update,
        time=dt.time(hour=9, tzinfo=pytz.timezone('Asia/Novosibirsk')),
        name="daily_stats_update"
    )
    application.job_queue.run_daily(
        daily_max_stats_update,
        time=dt.time(hour=9, minute=5, tzinfo=pytz.timezone('Asia/Novosibirsk')),
        name="daily_max_stats_update"
    )
    application.job_queue.run_daily(
        auto_max_stats_job,
        time=dt.time(hour=9, minute=35, tzinfo=pytz.timezone('Asia/Novosibirsk')),
        name="auto_max_stats"
    )

    application.post_init = on_start
    application.run_polling(stop_signals=None)



def main():
    run_telegram_bot()

if __name__ == "__main__":
    try:
        run_telegram_bot()
    except RuntimeError as e:
        if "event loop" in str(e):
            import nest_asyncio
            nest_asyncio.apply()
            run_telegram_bot()
