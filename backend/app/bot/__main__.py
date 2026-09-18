import asyncio
import logging

from ..core.config import settings
from ..core.db import init_mongo
from .client import VKClient
from .dispatcher import Dispatcher
from .handlers import register
from .longpoll import run_forever
from .pulse_bot import listen_events


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_mongo()
    if not settings.vk_token:
        logging.warning("VK_TOKEN пуст — бот не запущен")
        return
    dp = Dispatcher()
    register(dp)
    vk = VKClient()
    # long poll и pub/sub параллельно: long poll — входящие сообщения,
    # events — poll.published для рассылки
    await asyncio.gather(run_forever(vk, dp), listen_events(vk))


if __name__ == "__main__":
    asyncio.run(main())
