import asyncio
import logging

from ..core.config import settings
from .client import VKClient
from .dispatcher import Dispatcher
from .handlers import register
from .longpoll import run_forever


async def main():
    logging.basicConfig(level=logging.INFO)
    if not settings.vk_token:
        logging.warning("VK_TOKEN пуст — бот не запущен")
        return
    dp = Dispatcher()
    register(dp)
    await run_forever(VKClient(), dp)


if __name__ == "__main__":
    asyncio.run(main())
