import asyncio
import logging

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from .config import settings

log = logging.getLogger("db")

_motor_client: AsyncIOMotorClient | None = None


def get_motor_client() -> AsyncIOMotorClient:
    """Ленивый кэшированный клиент Mongo (beanie и gridfs живут на нём)."""
    global _motor_client
    if _motor_client is None:
        _motor_client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True)
    return _motor_client


def get_gridfs() -> AsyncIOMotorGridFSBucket:
    """GridFS-бакет на дефолтной базе из MONGO_URL.

    ponytail: без инъекции клиента — в тестах GridFS не эмулируется,
    цикл загрузки/отдачи проверяем интеграционно (тест помечен skip).
    """
    return AsyncIOMotorGridFSBucket(get_motor_client().get_default_database())


async def init_mongo() -> None:
    """Подключение к Mongo + инициализация Beanie. Вызывать на старте (api, бот, тесты).

    Если Mongo ещё не готова (соседний контейнер стартует) — ждём, а не падаем.
    """
    from ..modules.pulse.models import Poll, PollAnswer  # noqa: PLC0415
    from ..modules.bridge.models import (Ban, HelpRequest, HelperTopic,  # noqa: PLC0415
                                         PairMessage, Report, StopWord, TutorPair)
    from ..modules.duty.models import DutyCompletion, DutySchedule, DutyZone  # noqa: PLC0415
    from ..modules.navigator.models import Building, Floor, Room  # noqa: PLC0415
    from ..modules.users.models import SchoolClass, User  # noqa: PLC0415 — циклический импорт на уровне модуля

    client = get_motor_client()
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
        HelperTopic, HelpRequest, TutorPair, PairMessage, Report, Ban, StopWord,
        DutyZone, DutySchedule, DutyCompletion,
        Building, Floor, Room])
