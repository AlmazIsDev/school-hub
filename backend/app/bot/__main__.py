import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ..core import events
from ..core.config import settings
from ..core.db import init_mongo
from ..modules.media.models import Post
from . import duty_bot, media_bot, pulse_bot
from .client import VKClient
from .dispatcher import Dispatcher
from .handlers import register
from .longpoll import run_forever

REMIND_EVERY = 300  # сек: цикл напоминаний duty
# TTL дедуп-ключа media_bot — дольше этого срока анонс не догоняем
MEDIA_CATCHUP_WINDOW = 604800


async def duty_loop(vk):
    while True:
        try:
            await duty_bot.duty_tick(datetime.now(timezone.utc), vk)
        except Exception:
            logging.getLogger("bot").exception("duty_tick упал")
        await asyncio.sleep(REMIND_EVERY)


async def catch_up_media(vk):
    """Догонялка media.published: анонсы, потерянные пока бот был выключен.
    Дедуп-ключ не даёт отправить анонс второй раз."""
    since = datetime.now(timezone.utc) - timedelta(seconds=MEDIA_CATCHUP_WINDOW)
    posts = await Post.find(Post.status == "published", Post.published_at >= since).to_list()
    for post in posts:
        await media_bot.on_published({"post_id": str(post.id)}, vk)


async def main():
    logging.basicConfig(level=logging.INFO)
    await init_mongo()
    if not settings.vk_token:
        logging.warning("VK_TOKEN пуст — бот не запущен")
        return
    events.subscribe("poll.published", pulse_bot.on_published)
    events.subscribe("media.published", media_bot.on_published)
    dp = Dispatcher()
    register(dp)
    vk = VKClient()
    # pub/sub не персистентен: догоняем рассылки, чьи события ушли,
    # пока бот был выключен
    await pulse_bot.catch_up_unnotified(vk)
    await catch_up_media(vk)
    # long poll и pub/sub параллельно: long poll — входящие сообщения,
    # events — рассылки; напоминания duty — отдельная таска, без планировщика
    await asyncio.gather(run_forever(vk, dp), events.listen(vk), duty_loop(vk))


if __name__ == "__main__":
    asyncio.run(main())
