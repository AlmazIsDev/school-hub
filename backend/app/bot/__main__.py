import asyncio
import logging
from datetime import datetime, timezone

from ..core.config import settings
from ..core.db import init_mongo
from . import duty_bot
from .client import VKClient
from .dispatcher import Dispatcher
from .handlers import register
from .longpoll import run_forever
from .pulse_bot import catch_up_unnotified, listen_events

REMIND_EVERY = 300  # сек: цикл напоминаний duty


async def duty_loop(vk):
    while True:
        try:
            await duty_bot.duty_tick(datetime.now(timezone.utc), vk)
        except Exception:
            logging.getLogger("bot").exception("duty_tick упал")
        await asyncio.sleep(REMIND_EVERY)


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_mongo()
    if not settings.vk_token:
        logging.warning("VK_TOKEN пуст — бот не запущен")
        return
    dp = Dispatcher()
    register(dp)
    vk = VKClient()
    # pub/sub не персистентен: опубликуем рассылку для опросов, чьи события
    # ушли, пока бот был выключен
    await catch_up_unnotified(vk)
    # long poll и pub/sub параллельно: long poll — входящие сообщения,
    # events — poll.published для рассылки
    # напоминания duty — отдельная таска, без планировщика
    await asyncio.gather(run_forever(vk, dp), listen_events(vk), duty_loop(vk))


if __name__ == "__main__":
    asyncio.run(main())
