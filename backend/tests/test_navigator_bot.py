from conftest import ensure_school
import re

import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from app.bot import navigator_bot
from app.modules.navigator.models import Building, Floor, Room
from app.modules.users.models import School, User


class FakeVK:
    def __init__(self):
        self.messages: list[str] = []

    async def call(self, method, **params):
        if method == "messages.send":
            self.messages.append(params["message"])


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[School, User, Building, Floor, Room])
    yield


@pytest_asyncio.fixture
async def school(db):
    await User(school_id=await ensure_school(), login="s100", password_hash="x",
               full_name="Ученик", role="student", vk_id=100).insert()
    b = Building(school_id=await ensure_school(), name="Основное", address="ул. Школьная 1")
    await b.insert()
    f = Floor(school_id=await ensure_school(), building_id=str(b.id), level=2)
    await f.insert()
    room = Room(school_id=await ensure_school(), floor_id=str(f.id), number="205", name="Информатика",
                geometry={"type": "Polygon",
                          "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]})
    await room.insert()
    return b, f, room


def _event(text):
    m = re.match(r"^где\s+(.+)$", text, re.DOTALL | re.IGNORECASE)
    return {"vk_user_id": 100, "peer_id": 100, "match": m}


@pytest_asyncio.fixture
async def vk():
    return FakeVK()


async def test_found_by_number(db, school):
    vk = FakeVK()
    await navigator_bot.handle_where(_event("где 205"), vk)
    assert "205 «Информатика» - Основное, 2 этаж" in vk.messages[0]


async def test_found_by_name(db, school):
    vk = FakeVK()
    await navigator_bot.handle_where(_event("где информатика"), vk)
    assert "205" in vk.messages[0]


async def test_not_found(db, school):
    vk = FakeVK()
    await navigator_bot.handle_where(_event("где 999"), vk)
    assert "не нашла" in vk.messages[0].lower()
