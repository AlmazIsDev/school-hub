import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer
from app.modules.bridge.models import (Ban, HelpRequest, HelperTopic, PairMessage,
                                       Report, StopWord, TutorPair)

ALL_MODELS = [User, SchoolClass, Poll, PollAnswer,
              HelperTopic, HelpRequest, TutorPair, PairMessage, Report, Ban, StopWord]


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"), document_models=ALL_MODELS)
    yield


@pytest_asyncio.fixture
async def client(db):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _mk_user(login: str, role: str, full_name: str = "У") -> str:
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    u, _ = await create_user(login=login, full_name=full_name, role=role)
    return make_tokens(u.id, u.role)["access"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _mk_report(reported_id: str) -> str:
    r = Report(reporter_id="r" * 24, reported_user_id=reported_id, reason="мат")
    await r.insert()
    return str(r.id)


async def test_student_403_on_all_admin_routes(client, db):
    sh = _h(await _mk_user("s1", "student"))
    for method, url in [
        ("get", "/api/bridge/reports"),
        ("post", "/api/bridge/reports/x/resolve"),
        ("get", "/api/bridge/bans"),
        ("delete", "/api/bridge/bans/x"),
        ("get", "/api/bridge/stop-words"),
        ("post", "/api/bridge/stop-words"),
        ("delete", "/api/bridge/stop-words/x"),
        ("get", "/api/bridge/helpers"),
    ]:
        r = await getattr(client, method)(url, headers=sh)
        assert r.status_code == 403, f"{method} {url} -> {r.status_code}"


async def test_resolve_dismiss(client, db):
    th = _h(await _mk_user("t1", "teacher"))
    rid = await _mk_report("u" * 24)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "dismiss"}, headers=th)
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    assert await Ban.find_all().to_list() == []


async def test_resolve_ban_days(client, db):
    th = _h(await _mk_user("t2", "teacher"))
    from app.modules.users.service import create_user
    u, _ = await create_user(login="bad1", full_name="Вредитель", role="student")
    uid = str(u.id)
    rid = await _mk_report(uid)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "ban_days", "days": 7}, headers=th)
    assert r.status_code == 200
    bans = await Ban.find_all().to_list()
    assert len(bans) == 1 and bans[0].user_id == uid and bans[0].until is not None
    # reported_full_name виден в списке жалоб
    r = await client.get("/api/bridge/reports?status=resolved", headers=th)
    assert r.status_code == 200 and r.json()[0]["reported_full_name"] == "Вредитель"


async def test_resolve_ban_forever(client, db):
    th = _h(await _mk_user("t3", "teacher"))
    rid = await _mk_report("u" * 24)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "ban_forever"}, headers=th)
    assert r.status_code == 200
    bans = await Ban.find_all().to_list()
    assert len(bans) == 1 and bans[0].until is None


async def test_resolve_ban_days_without_days_422(client, db):
    th = _h(await _mk_user("t4", "teacher"))
    rid = await _mk_report("u" * 24)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "ban_days"}, headers=th)
    assert r.status_code == 422


async def test_resolve_bad_days_422(client, db):
    th = _h(await _mk_user("t5", "teacher"))
    rid = await _mk_report("u" * 24)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "ban_days", "days": 0}, headers=th)
    assert r.status_code == 422


async def test_resolve_twice_409(client, db):
    th = _h(await _mk_user("t6", "teacher"))
    rid = await _mk_report("u" * 24)
    await client.post(f"/api/bridge/reports/{rid}/resolve", json={"action": "dismiss"}, headers=th)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve", json={"action": "dismiss"}, headers=th)
    assert r.status_code == 409


async def test_resolve_unknown_404(client, db):
    th = _h(await _mk_user("t7", "teacher"))
    r = await client.post(f"/api/bridge/reports/{'f' * 24}/resolve",
                          json={"action": "dismiss"}, headers=th)
    assert r.status_code == 404


async def test_bans_list_and_delete(client, db):
    th = _h(await _mk_user("t8", "teacher"))
    await Ban(user_id="u" * 24, until=None, reason="тест").insert()
    r = await client.get("/api/bridge/bans", headers=th)
    assert r.status_code == 200 and len(r.json()) == 1
    ban_id = r.json()[0]["id"]
    r = await client.delete(f"/api/bridge/bans/{ban_id}", headers=th)
    assert r.status_code == 200
    assert await Ban.find_all().to_list() == []


async def test_stop_words_crud_and_duplicate_409(client, db):
    ah = _h(await _mk_user("a1", "admin"))
    r = await client.post("/api/bridge/stop-words", json={"word": "  МАТ  "}, headers=ah)
    assert r.status_code == 200 and r.json()["word"] == "мат"
    r = await client.post("/api/bridge/stop-words", json={"word": "мат"}, headers=ah)
    assert r.status_code == 409
    r = await client.post("/api/bridge/stop-words", json={"word": "  "}, headers=ah)
    assert r.status_code == 422
    wid = (await client.get("/api/bridge/stop-words", headers=ah)).json()[0]["id"]
    r = await client.delete(f"/api/bridge/stop-words/{wid}", headers=ah)
    assert r.status_code == 200
    assert await StopWord.find_all().to_list() == []


async def test_stop_words_teacher_403(client, db):
    th = _h(await _mk_user("t9", "teacher"))
    r = await client.post("/api/bridge/stop-words", json={"word": "х"}, headers=th)
    assert r.status_code == 403
    r = await client.get("/api/bridge/stop-words", headers=th)
    assert r.status_code == 403


async def test_check_text(client, db):
    from app.modules.bridge.service import check_text
    await StopWord(word="мат").insert()
    assert await check_text("Привет, как дела?") is True
    assert await check_text("Какой-то МАТ тут") is False


async def test_helpers_rating(client, db):
    th = _h(await _mk_user("t10", "teacher"))
    from app.modules.users.service import create_user, by_login
    await create_user(login="s2", full_name="Помощник", role="student")
    helper_id = str((await by_login("s2")).id)
    await HelperTopic(user_id=helper_id, topic="алгебра").insert()
    await HelperTopic(user_id=helper_id, topic="геометрия").insert()
    await TutorPair(request_id=None, helper_id=helper_id, seeker_id="s" * 24,
                    chat_key="k1", status="closed", helper_score=5).insert()
    await TutorPair(request_id=None, helper_id=helper_id, seeker_id="s" * 24,
                    chat_key="k2", status="closed", helper_score=3).insert()
    # активная пара и пара без оценки не считаются в среднее, но закрытая без оценки — в pairs
    await TutorPair(request_id=None, helper_id=helper_id, seeker_id="s" * 24,
                    chat_key="k3", status="active").insert()
    await TutorPair(request_id=None, helper_id=helper_id, seeker_id="s" * 24,
                    chat_key="k4", status="closed", helper_score=None).insert()
    r = await client.get("/api/bridge/helpers", headers=th)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == helper_id and row["full_name"] == "Помощник"
    assert row["topics"] == ["алгебра", "геометрия"]
    assert row["pairs"] == 3  # только закрытые
    assert row["avg_score"] == 4.0


async def test_resolve_invalid_action_422(client, db):
    th = _h(await _mk_user("t3", "teacher"))
    rid = await _mk_report("u" * 24)
    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "banana"}, headers=th)
    assert r.status_code == 422

    r = await client.post(f"/api/bridge/reports/{rid}/resolve",
                          json={"action": "ban_days", "days": 99999}, headers=th)
    assert r.status_code == 422
