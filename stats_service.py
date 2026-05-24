
# -*- coding: utf-8 -*-
import logging
import threading

import uvicorn
from fastapi import FastAPI

from chanhistory import run_telegram_bot
from config import MAX_STATS_PORT
from logging_config import setup_logger
from max_members_polling import run_max_members_polling_loop
from max_stats_webhook import app as max_app

setup_logger()
logger = logging.getLogger(__name__)

telegram_thread = None
polling_thread = None


def _telegram_runner() -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        run_telegram_bot()
    except Exception:
        logger.exception("Telegram stats bot stopped with error")
    finally:
        try:
            loop.close()
        except Exception:
            logger.exception("Failed to close telegram event loop")


def _max_polling_runner() -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        run_max_members_polling_loop()
    except Exception:
        logger.exception("MAX members polling stopped with error")
    finally:
        try:
            loop.close()
        except Exception:
            logger.exception("Failed to close MAX polling event loop")


app = FastAPI(title="Stats Service")
app.mount("/", max_app)


@app.on_event("startup")
async def startup_event():
    global telegram_thread, polling_thread
    if telegram_thread is None or not telegram_thread.is_alive():
        telegram_thread = threading.Thread(target=_telegram_runner, daemon=True, name="telegram-stats-bot")
        telegram_thread.start()
        logger.info("Telegram stats bot thread started")
    if polling_thread is None or not polling_thread.is_alive():
        polling_thread = threading.Thread(target=_max_polling_runner, daemon=True, name="max-members-polling")
        polling_thread.start()
        logger.info("MAX members polling thread started")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("stats_service:app", host="0.0.0.0", port=int(MAX_STATS_PORT), reload=False)
