from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings


async def init_mongo() -> None:
    """Подключение к Mongo + инициализация Beanie. Вызывать на старте (api, бот, тесты)."""
    from ..modules.users.models import SchoolClass, User  # noqa: PLC0415 — циклический импорт на уровне модуля

    client = AsyncIOMotorClient(settings.mongo_url)
    await init_beanie(client.get_default_database(), document_models=[User, SchoolClass])
