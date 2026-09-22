import os

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret")

from mongomock_motor import AsyncMongoMockClient
import pytest_asyncio
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import School, SchoolClass, User
from app.modules.media.models import Post, PostIdea


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[School, User, SchoolClass, Post, PostIdea])
    yield


async def ensure_school() -> str:
    """Школа «s1» для тестов: создаётся лениво, возвращает реальный _id."""
    s = await School.find_one(School.code == "s1")
    if not s:
        s = await School(name="Школа", code="s1").insert()
    return str(s.id)


@pytest_asyncio.fixture
async def client(db):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
