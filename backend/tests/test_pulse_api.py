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


async def test_publish_sends_event(client, db, monkeypatch):
    h = {"Authorization": f"Bearer {await _mk_user('t8', 'teacher')}"}
    pid = await _mk_poll(client, h, await _mk_class())
    sent = []

    class FakeRedis:
        async def publish(self, channel: str, payload: str):
            sent.append((channel, json.loads(payload)))

    monkeypatch.setattr(core_redis, "get_redis", lambda: FakeRedis())
    r = await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
    assert r.status_code == 200
    assert sent == [("events", {"type": "poll.published", "poll_id": pid})]


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


# ---- T4: аналитика ----

async def _mk_poll_full(client, h, class_id, topic="Тема", questions=None) -> str:
    body = {"title": "Опрос", "topic": topic, "class_id": class_id,
            "questions": questions or [{"text": "Как дела?", "type": "scale1_5"}]}
    r = await client.post("/api/pulse/polls", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _answer(pid: str, qidx: int, value: str):
    await PollAnswer(poll_id=pid, question_idx=qidx, value=value).insert()


async def test_results_scale_counts_and_free_text(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t10', 'teacher')}"}
    cid = await _mk_class()
    pid = await _mk_poll_full(client, h, cid, questions=[
        {"text": "Шкала", "type": "scale1_5"},
        {"text": "Текст", "type": "free_text"},
    ])
    await _answer(pid, 0, "1"); await _answer(pid, 0, "5"); await _answer(pid, 0, "5")
    await _answer(pid, 1, "норм"); await _answer(pid, 1, "можно лучше")
    # мусорное значение шкалы — не в counts
    await _answer(pid, 0, "9")
    r = await client.get(f"/api/pulse/polls/{pid}/results", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["poll"]["status"] == "draft"  # результаты доступны и до закрытия
    assert data["questions"][0]["answers"] == {"1": 1, "2": 0, "3": 0, "4": 0, "5": 2}
    assert data["questions"][1]["answers"] == ["норм", "можно лучше"]
    # "9" тоже ответ (бот такое не присылает, но считать честно)
    assert data["started"] == 4 and data["completed"] == 2


async def test_results_partial_completion(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t11', 'teacher')}"}
    pid = await _mk_poll_full(client, h, await _mk_class(), questions=[
        {"text": "Ш1", "type": "scale1_5"},
        {"text": "Ш2", "type": "scale1_5"},
    ])
    await _answer(pid, 0, "3")
    await _answer(pid, 0, "4"); await _answer(pid, 1, "2")
    r = await client.get(f"/api/pulse/polls/{pid}/results", headers=h)
    data = r.json()
    assert data["started"] == 2 and data["completed"] == 1


async def test_results_student_403(client, db):
    th = {"Authorization": f"Bearer {await _mk_user('t12', 'teacher')}"}
    sh = {"Authorization": f"Bearer {await _mk_user('s10', 'student')}"}
    pid = await _mk_poll_full(client, th, await _mk_class())
    r = await client.get(f"/api/pulse/polls/{pid}/results", headers=sh)
    assert r.status_code == 403


async def test_results_other_teacher_403(client, db):
    owner = {"Authorization": f"Bearer {await _mk_user('t13', 'teacher')}"}
    other = {"Authorization": f"Bearer {await _mk_user('t14', 'teacher')}"}
    pid = await _mk_poll_full(client, owner, await _mk_class())
    r = await client.get(f"/api/pulse/polls/{pid}/results", headers=other)
    assert r.status_code == 403


async def test_topics_threshold_filter(client, db):
    good_h = {"Authorization": f"Bearer {await _mk_user('t15', 'teacher')}"}
    cid = await _mk_class()
    # avg 4.0 — не попадёт
    good = await _mk_poll_full(client, good_h, cid, topic="Хорошая")
    for v in ("4", "4", "4", "4"):
        await _answer(good, 0, v)
    # avg 2.5 — попадёт
    bad = await _mk_poll_full(client, good_h, cid, topic="Плохая")
    for v in ("2", "3"):
        await _answer(bad, 0, v)
    await client.post(f"/api/pulse/polls/{good}/publish", headers=good_h)
    await client.post(f"/api/pulse/polls/{good}/close", headers=good_h)
    await client.post(f"/api/pulse/polls/{bad}/publish", headers=good_h)
    await client.post(f"/api/pulse/polls/{bad}/close", headers=good_h)
    r = await client.get("/api/pulse/topics", headers=good_h)
    assert r.status_code == 200
    rows = r.json()
    assert [x["topic"] for x in rows] == ["Плохая"]
    assert rows[0]["avg"] == 2.5 and rows[0]["n_answers"] == 2
    # активный опрос не попадает
    open_pid = await _mk_poll_full(client, good_h, cid, topic="Открытая")
    await client.post(f"/api/pulse/polls/{open_pid}/publish", headers=good_h)
    for v in ("1", "1"):
        await _answer(open_pid, 0, v)
    r = await client.get("/api/pulse/topics", headers=good_h)
    assert "Открытая" not in [x["topic"] for x in r.json()]


async def test_topics_threshold_validation(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t16', 'teacher')}"}
    r = await client.get("/api/pulse/topics?threshold=9", headers=h)
    assert r.status_code == 422


async def test_compare_ok(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t17', 'teacher')}"}
    cid = await _mk_class()
    qa = await _mk_poll_full(client, h, cid, topic="Оценки", questions=[
        {"text": "Шкала", "type": "scale1_5"},
        {"text": "Текст", "type": "free_text"},
    ])
    qb = await _mk_poll_full(client, h, cid, topic="Оценки", questions=[
        {"text": "Шкала", "type": "scale1_5"},
        {"text": "Текст", "type": "free_text"},
    ])
    for pid in (qa, qb):
        await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
        await client.post(f"/api/pulse/polls/{pid}/close", headers=h)
    await _answer(qa, 0, "2"); await _answer(qa, 0, "4")
    await _answer(qb, 0, "5")
    r = await client.get(f"/api/pulse/compare?a={qa}&b={qb}", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["a"]["avgs"] == [3.0]
    assert data["b"]["avgs"] == [5.0]


async def test_compare_different_topics_400(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t18', 'teacher')}"}
    cid = await _mk_class()
    qa = await _mk_poll_full(client, h, cid, topic="Т1")
    qb = await _mk_poll_full(client, h, cid, topic="Т2")
    for pid in (qa, qb):
        await client.post(f"/api/pulse/polls/{pid}/publish", headers=h)
        await client.post(f"/api/pulse/polls/{pid}/close", headers=h)
    r = await client.get(f"/api/pulse/compare?a={qa}&b={qb}", headers=h)
    assert r.status_code == 400


async def test_compare_not_closed_409(client, db):
    h = {"Authorization": f"Bearer {await _mk_user('t19', 'teacher')}"}
    cid = await _mk_class()
    qa = await _mk_poll_full(client, h, cid, topic="Т")
    qb = await _mk_poll_full(client, h, cid, topic="Т")
    await client.post(f"/api/pulse/polls/{qa}/publish", headers=h)
    await client.post(f"/api/pulse/polls/{qa}/close", headers=h)
    r = await client.get(f"/api/pulse/compare?a={qa}&b={qb}", headers=h)
    assert r.status_code == 409
