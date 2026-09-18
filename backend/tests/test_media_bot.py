import re

import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from app.bot import media_bot
from app.core import redis as core_redis
from app.modules.media.models import Post, PostIdea
from app.modules.users.models import User


class FakeRedis:
    async def publish(self, channel, message):
        self.published = (channel, message)


class FakeVK:
    def __init__(self):
        self.calls: list[dict] = []

    async def call(self, method, **params):
        self.calls.append({"method": method, **params})


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[User, Post, PostIdea])
    yield


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(core_redis, "get_redis", lambda: fr)
    monkeypatch.setattr(media_bot, "_r", lambda: fr)
    return fr


@pytest_asyncio.fixture
async def vk():
    return FakeVK()


async def _mk_user(role="student", vk_id=100, full_name="У") -> User:
    u = User(login=f"l{vk_id}{role}", password_hash="x", full_name=full_name,
             role=role, vk_id=vk_id)
    await u.insert()
    return u


def _idea_event(text):
    m = re.match(r"^идея\s+(.+)$", text, re.DOTALL | re.IGNORECASE)
    return {"vk_user_id": 100, "peer_id": 100, "match": m}


async def test_idea_truncated_to_1000(db, fake_redis, vk):
    u = await _mk_user()
    await media_bot.handle_idea(_idea_event("идея " + "а" * 1500), vk)
    ideas = await PostIdea.find_all().to_list()
    assert len(ideas) == 1
    assert ideas[0].text == "а" * 1000
    assert ideas[0].author_id == str(u.id)
    assert vk.calls[0]["message"] == media_bot.IDEA_SENT


async def test_idea_notifies_editors(db, fake_redis, vk):
    await _mk_user(role="student", vk_id=100, full_name="Вася")
    t1 = await _mk_user(role="teacher", vk_id=201, full_name="Т1")
    t2 = await _mk_user(role="teacher", vk_id=202, full_name="Т2")
    await _mk_user(role="teacher", vk_id=None)  # без vk — не спамим
    await _mk_user(role="student", vk_id=300)  # ученик — не редактор
    await media_bot.handle_idea(_idea_event("идея Про школу"), vk)
    editor_msgs = [c for c in vk.calls if c["peer_id"] in (201, 202)]
    assert len(editor_msgs) == 2
    assert all(c["message"] == "Новая идея от Вася: Про школу" for c in editor_msgs)
    assert not any(c["peer_id"] == 300 for c in vk.calls)


async def test_idea_editors_limited_to_10(db, fake_redis, vk):
    await _mk_user(role="student", vk_id=100, full_name="Вася")
    for i in range(12):
        await _mk_user(role="teacher", vk_id=200 + i)
    await media_bot.handle_idea(_idea_event("идея X"), vk)
    editor_msgs = [c for c in vk.calls if c["peer_id"] != 100]
    assert len(editor_msgs) == 10


async def test_idea_unbound_gets_hint(db, fake_redis, vk):
    await media_bot.handle_idea(_idea_event("идея Привет"), vk)
    assert vk.calls[0]["message"] == media_bot.NOT_BOUND
    assert await PostIdea.find_all().to_list() == []


async def test_published_broadcast(db, fake_redis, vk):
    await _mk_user(role="student", vk_id=100)
    await _mk_user(role="student", vk_id=200)
    await _mk_user(role="student", vk_id=None)  # без vk — мимо
    await _mk_user(role="teacher", vk_id=300)  # учитель — мимо
    post = await Post(title="Т", body="Б" * 500, status="published").insert()
    await media_bot.on_published({"post_id": str(post.id)}, vk)
    peers = [c["peer_id"] for c in vk.calls]
    assert sorted(peers) == [100, 200]
    msg = vk.calls[0]["message"]
    assert "Т" in msg and "Б" * 400 in msg and "Полностью — на сайте" in msg


async def test_published_broken_event_silent(db, fake_redis, vk):
    await _mk_user(role="student", vk_id=100)
    await media_bot.on_published({"post_id": "не-objectid"}, vk)
    await media_bot.on_published({"post_id": None}, vk)
    await media_bot.on_published({}, vk)
    assert vk.calls == []
