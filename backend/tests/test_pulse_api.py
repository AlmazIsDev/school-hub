import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer


# conftest-овые db/client не знают про pulse-коллекции — перекрываем локально
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


POLL = {"title": "Опрос", "topic": "Д POLL", "class_id": "c1",
        "questions": [{"text": "Как дела?", "type": "scale1_5"}]}


async def test_student_cannot_create(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('s1', 'student')}"}
    r = await client.post("/api/pulse/polls", json=POLL, headers=h)
    assert r.status_code == 403


async def test_teacher_create_publish_close(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t1', 'teacher')}"}
    r = await client.post("/api/pulse/polls", json=POLL, headers=h)
    assert r.status_code == 200
    pid = r.json()["id"]
    r = await client.get(f"/api/pulse/polls/{pid}", headers=h)
    assert r.json()["status"] == "draft"
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
    assert r.json()["status"] == "active"
    r = await client.post(f"/api/pulse/polls/{pid}/close", headers=h)
    assert r.json()["status"] == "closed" and r.json()["closed_at"]
    r = await client.post(f"/api/pulse/polls/{pid}/close", headers=h)
    assert r.status_code == 409


async def test_publish_not_owner_403(client, db):
    owner = {"Authorization": f"Bearer {await _mk_user('t2', 'teacher')}"}
    other = {"Authorization": f"Bearer {await _mk_user('t3', 'teacher')}"}
    pid = (await client.post("/api/pulse/polls", json=POLL, headers=owner)).json()["id"]
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=other)
    assert r.status_code == 403


async def test_student_sees_only_active_own_class(client, db):
    ch = {"Authorization": f"Bearer {await _mk_user('t4', 'teacher')}"}
    sh = {"Authorization": f"Bearer {await _mk_user('s2', 'student', class_id='c1')}"}
    pid = (await client.post("/api/pulse/polls", json=POLL, headers=ch)).json()["id"]
    # draft — ученику не виден ни в списке, ни напрямую
    r = await client.get("/api/pulse/polls", headers=sh)
    assert r.json() == []
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
    assert r.json() == []


async def test_admin_can_publish_any(client, db):
    th = {"Authorization": f"Bearer {await _mk_user('t5', 'teacher')}"}
    ah = {"Authorization": f"Bearer {await _mk_user('a1', 'admin')}"}
    pid = (await client.post("/api/pulse/polls", json=POLL, headers=th)).json()["id"]
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=ah)
    assert r.status_code == 200 and r.json()["status"] == "active"
