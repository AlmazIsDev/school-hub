import json

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.core import redis as core_redis
from app.modules.users.models import SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer


# conftest db/client don't know pulse collections - override locally
@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[User, SchoolClass, Poll, PollAnswer])
    yield


@pytest_asyncio.fixture
async def client(db):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _mk_user(login: str, role: str, class_id: str | None = None) -> str:
    """Создаёт пользователя и возвращает access-токен."""
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    u, _ = await create_user(login=login, full_name="У", role=role, class_id=class_id)
    return make_tokens(u.id, u.role)["access"]


async def _mk_class(grade: int = 9, letter: str = "А") -> str:
    c = SchoolClass(grade=grade, letter=letter)
    await c.insert()
    return str(c.id)


POLL = {"title": "Опрос", "topic": "Тема", "class_id": None,
        "questions": [{"text": "Как дела?", "type": "scale1_5"}]}


async def _mk_poll(client, h: dict, class_id: str) -> str:
    r = await client.post("/api/pulse/polls", json={**POLL, "class_id": class_id}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_student_cannot_create(client, db):
    class_id = await _mk_class()
    h = {"Authorization": f"Bearer {await _mk_user('s1', 'student')}"}
    r = await client.post("/api/pulse/polls", json={**POLL, "class_id": class_id}, headers=h)
    assert r.status_code == 403
    assert r.json() == {"detail": "Недостаточно прав"}


async def test_create_unknown_class_404(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t0', 'teacher')}"}
    r = await client.post("/api/pulse/polls", json={**POLL, "class_id": "0" * 24}, headers=h)
    assert r.status_code == 404
    assert r.json() == {"detail": "Класс не найден"}


async def test_teacher_create_publish_close(client, db, monkeypatch):
    h = {"Authorization": f"Bearer {await _mk_user('t1', 'teacher')}"}
    pid = await _mk_poll(client, h, await _mk_class())
    r = await client.get(f"/api/pulse/polls/{pid}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "draft"
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "active"
    # фейк-redis: poll.closed должен уйти в канал "events"
    sent = []

    class FakeRedis:
        async def publish(self, channel: str, payload: str):
            sent.append((channel, json.loads(payload)))

    monkeypatch.setattr(core_redis, "get_redis", lambda: FakeRedis())
    r = await client.post(f"/api/pulse/polls/{pid}/close", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "closed" and r.json()["closed_at"]
    assert sent == [("events", {"type": "poll.closed", "poll_id": pid})]


async def test_publish_not_owner_403(client, db):
    owner = {"Authorization": f"Bearer {await _mk_user('t2', 'teacher')}"}
    other = {"Authorization": f"Bearer {await _mk_user('t3', 'teacher')}"}
    pid = await _mk_poll(client, owner, await _mk_class())
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=other)
    assert r.status_code == 403
    assert r.json() == {"detail": "Не ваш опрос"}


async def test_publish_closed_409(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t6', 'teacher')}"}
    pid = await _mk_poll(client, h, await _mk_class())
    await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
    await client.post(f"/api/pulse/polls/{pid}/close", headers=h)
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
    assert r.status_code == 409
    assert r.json() == {"detail": "Опрос закрыт"}


async def test_student_sees_only_active_own_class(client, db):
    ch = {"Authorization": f"Bearer {await _mk_user('t4', 'teacher')}"}
    cid = await _mk_class()
    sh = {"Authorization": f"Bearer {await _mk_user('s2', 'student', class_id=cid)}"}
    pid = await _mk_poll(client, ch, cid)
    # draft — ученику не виден ни в списке, ни напрямую
    r = await client.get("/api/pulse/polls", headers=sh)
    assert r.status_code == 200 and r.json() == []
    r = await client.get(f"/api/pulse/polls/{pid}", headers=sh)
    assert r.status_code == 403
    await client.post(f"/api/pulse/polls/{pid}/publish", headers=ch)
    r = await client.get("/api/pulse/polls", headers=sh)
    assert [p["id"] for p in r.json()] == [pid]
    r = await client.get(f"/api/pulse/polls/{pid}", headers=sh)
    assert r.status_code == 200
    # closed — снова не виден
    await client.post(f"/api/pulse/polls/{pid}/close", headers=ch)
    r = await client.get(f"/api/pulse/polls/{pid}", headers=sh)
    assert r.status_code == 403
    r = await client.get("/api/pulse/polls", headers=sh)
    assert r.status_code == 200 and r.json() == []


async def test_admin_sees_all_polls(client, db):
    th = {"Authorization": f"Bearer {await _mk_user('t5', 'teacher')}"}
    ah = {"Authorization": f"Bearer {await _mk_user('a1', 'admin')}"}
    cid = await _mk_class()
    pid = await _mk_poll(client, th, cid)
    r = await client.get("/api/pulse/polls", headers=ah)
    assert r.status_code == 200
    assert pid in [p["id"] for p in r.json()]


async def test_admin_can_publish_any(client, db):
    th = {"Authorization": f"Bearer {await _mk_user('t7', 'teacher')}"}
    ah = {"Authorization": f"Bearer {await _mk_user('a2', 'admin')}"}
    pid = await _mk_poll(client, th, await _mk_class())
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=ah)
    assert r.status_code == 200
    assert r.json()["status"] == "active"
