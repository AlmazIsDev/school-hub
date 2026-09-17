import asyncio
import logging

from .client import VKClient
from .dispatcher import Dispatcher
from .handlers import register
from .longpoll import run_forever


async def main():
    logging.basicConfig(level=logging.INFO)
    dp = Dispatcher()
    register(dp)
    await run_forever(VKClient(), dp)


if __name__ == "__main__":
    asyncio.run(main())
