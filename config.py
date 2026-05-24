import os

MAX_BOT_TOKEN = "f9LHodD0cOK5wiNNroyTn31pK-BxsJk-I1u657KbRBk2mvkLcoNvgdhsBHk9_TZ0yxd1d2GtnPrfmlnTSvWq"
MAX_BOT_API_BASE = "https://platform-api.max.ru"
MAX_WEBHOOK_SECRET = "a7b7c5f1d4e8a2b3c6d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1"
MAX_BOT_NAME = "id5408028308_1_bot"

MAX_SITE_API_KEY = "827f4c3f-4002-5052-9020-ed8e58d28320"
#MAX_SITE_AUTH_URL_INTERNAL = "http://10.0.44.16:7006/auth/max/complete"
#MAX_SITE_AUTH_URL_EXTERNAL = "https://koptorg.ru:7026/auth/max/complete"
MAX_SITE_AUTH_URL_INTERNAL = "http://10.0.44.11:8030/auth/max/complete"
MAX_SITE_AUTH_URL_EXTERNAL = "https://koptorg.ru/auth/max/complete"

MAX_REQUEST_TIMEOUT = 15
PORT = "8081"

# -----------------------------
# MAX stats bot
# -----------------------------
MAX_STATS_BOT_TOKEN = "f9LHodD0cOLUpWwHAkKm8RCG-S7VQlkmuY7_7VVUP8MqI9cBVynBIci33tpFjvMjFYT2ZgRlebe0zY7oAzM3"
MAX_STATS_BOT_API_BASE = MAX_BOT_API_BASE
MAX_STATS_WEBHOOK_SECRET = "max_stats_secret_2026_04_22"
MAX_STATS_BOT_NAME = "id5408028308_3_bot"
MAX_STATS_REQUEST_TIMEOUT = 45
MAX_STATS_PORT = "8083"
MAX_STATS_WEBHOOK_PATH = "/webhook/max_stats"
MAX_STATS_POLL_ENABLED = True
MAX_STATS_POLL_INTERVAL_SEC = 300
MAX_STATS_IGNORE_MESSAGE_CREATED = True

# Telegram stats bot proxy (used only by python-telegram-bot, not globally for the whole process)
TG_STATS_PROXY_URL = os.getenv("TG_STATS_PROXY_URL", "http://bot:kooptorg2026123MontyPython@62.60.229.9:80")

# -----------------------------
# Telegram notifications for MAX polling events
# -----------------------------
TG_NOTIFY_BOT_TOKEN = os.getenv("TG_NOTIFY_BOT_TOKEN", "7612731502:AAEs0DlxR15VlZKbn0X9W8oSpH8niUQXSXQ")
TG_NOTIFY_ADMIN_IDS = [200190627, 1389166185, 7591995723, 1001102821, 6248528837, 537341017, 1247091364]
TG_NOTIFY_PROXY_URL = os.getenv("TG_NOTIFY_PROXY_URL", "http://bot:kooptorg2026123MontyPython@62.60.229.9:80")
TG_NOTIFY_ENABLED = True
MAX_STATS_SKIP_INITIAL_SNAPSHOT_NOTIFICATIONS = True
