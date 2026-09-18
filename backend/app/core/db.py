import asyncio
import logging

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings

log = logging.getLogger("db")


async def init_mongo() -> None:
    """Подключение к Mongo + инициализация Beanie. Вызывать на старте (api, бот, тесты).

    Если Mongo ещё не готова (соседний контейнер стартует) — ждём, а не падаем.
    """
    from ..modules.pulse.models import Poll, PollAnswer  # noqa: PLC0415
    from ..modules.bridge.models import (Ban, HelpRequest, HelperTopic,  # noqa: PLC0415
                                         PairMessage, Report, StopWord, TutorPair)
    from ..modules.users.models import SchoolClass, User  # noqa: PLC0415 — циклический импорт на уровне модуля

    client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True)
    for attempt in range(1, 31):  # ~2.5 мин максимум
        try:
            await client.admin.command("ping")
            break
        except Exception as e:
            if attempt == 30:
                raise
            log.warning("mongo недоступна (попытка %d/30): %s", attempt, e)
            await asyncio.sleep(5)
    await init_beanie(client.get_default_database(), document_models=[
        User, SchoolClass, Poll, PollAnswer,
        HelperTopic, HelpRequest, TutorPair, PairMessage, Report, Ban, StopWord])
