"""Изоляция арендаторов: объект чужой школы неотличим от несуществующего."""
from conftest import ensure_school

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import School, SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer

ALL_MODELS = [School, User, SchoolClass, Poll, PollAnswer]


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


async def _teacher_of(school_code: str, login: str) -> str:
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    u, _ = await create_user(school_id=await ensure_school_by_code(school_code),
                             login=login, full_name="У", role="teacher")
    return make_tokens(u.id, u.role, u.school_id)["access"]


async def ensure_school_by_code(code: str) -> str:
    s = await School.find_one(School.code == code)
    if not s:
        s = await School(name=f"Школа {code}", code=code).insert()
    return str(s.id)


async def test_foreign_poll_is_404(client, db):
    sid_a = await ensure_school_by_code("aa")
    cls_a = await SchoolClass(school_id=sid_a, grade=9, letter="А").insert()
    t_a = await _teacher_of("aa", "ta")
    r = await client.post("/api/pulse/polls",
                          json={"title": "Опрос", "topic": "Т", "class_id": str(cls_a.id),
                                "questions": [{"text": "Как дела?", "type": "scale1_5"}]},
                          headers={"Authorization": f"Bearer {t_a}"})
    assert r.status_code == 200
    poll_id = r.json()["id"]

    # учитель школы bb не видит опрос школы aa
    await ensure_school_by_code("bb")
    t_b = await _teacher_of("bb", "tb")
    r = await client.get(f"/api/pulse/polls/{poll_id}",
                         headers={"Authorization": f"Bearer {t_b}"})
    assert r.status_code == 404
    r = await client.post(f"/api/pulse/polls/{poll_id}/close",
                          headers={"Authorization": f"Bearer {t_b}"})
    assert r.status_code == 404


async def test_superadmin_login_without_school_code(client, db):
    """Платформенный админ входит с пустым кодом школы."""
    from app.modules.users.models import User
    from app.core.auth import hash_password
    await User(login="root", password_hash=hash_password("pw123456"),
               full_name="Root", role="superadmin").insert()
    r = await client.post("/api/auth/login",
                          json={"school_code": "", "login": "root", "password": "pw123456"})
    assert r.status_code == 200
    r = await client.post("/api/auth/login",
                          json={"school_code": "aa", "login": "root", "password": "pw123456"})
    assert r.status_code == 401  # под кодом школы его нет


async def test_superadmin_school_context_header(client, db):
    """X-School-Id переключает контекст superadmin'а: без него — общая база, с ним — школа."""
    from app.modules.users.models import User
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens, hash_password
    sid_a = await ensure_school_by_code("aa")
    await create_user(school_id=sid_a, login="a1", full_name="А", role="student")
    await User(login="root", password_hash=hash_password("pw123456"),
               full_name="Root", role="superadmin").insert()
    r = await client.post("/api/auth/login",
                          json={"school_code": "", "login": "root", "password": "pw123456"})
    h = {"Authorization": f"Bearer {r.json()['access']}"}
    # без заголовка — все пользователи всех школ
    r = await client.get("/api/users", headers=h)
    assert any(u["login"] == "a1" for u in r.json())
    # с заголовком — только выбранная школа
    r = await client.get("/api/users", headers={**h, "X-School-Id": sid_a})
    assert [u["login"] for u in r.json()] == ["a1"]


async def test_login_wrong_school_code_401(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school_by_code("aa"),
                               login="s2", full_name="У", role="student")
    r = await client.post("/api/auth/login",
                          json={"school_code": "bb", "login": "s2", "password": tmp})
    assert r.status_code == 401


async def test_users_list_scoped_by_school(client, db):
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    sid_a = await ensure_school_by_code("aa")
    sid_b = await ensure_school_by_code("bb")
    await create_user(school_id=sid_a, login="only_a", full_name="А", role="student")
    adm, _ = await create_user(school_id=sid_b, login="adm_b", full_name="Б", role="admin")
    h = {"Authorization": f"Bearer {make_tokens(adm.id, adm.role, adm.school_id)['access']}"}
    r = await client.get("/api/users", headers=h)
    logins = [u["login"] for u in r.json()]
    assert "only_a" not in logins and "adm_b" in logins


async def test_poll_answers_scoped_by_school(client, db):
    """Анонимные ответы несут school_id: учитель чужой школы не увидит их в агрегатах."""
    sid_a = await ensure_school_by_code("aa")
    sid_b = await ensure_school_by_code("bb")
    cls_a = await SchoolClass(school_id=sid_a, grade=8, letter="Б").insert()
    t_a = await _teacher_of("aa", "ta2")
    r = await client.post("/api/pulse/polls",
                          json={"title": "О", "topic": "Т", "class_id": str(cls_a.id),
                                "questions": [{"text": "Шкала", "type": "scale1_5"}]},
                          headers={"Authorization": f"Bearer {t_a}"})
    poll_id = r.json()["id"]
    await PollAnswer(school_id=sid_a, poll_id=poll_id, question_idx=0, value="5").insert()
    await PollAnswer(school_id=sid_b, poll_id=poll_id, question_idx=0, value="1").insert()
    r = await client.get(f"/api/pulse/polls/{poll_id}/results",
                         headers={"Authorization": f"Bearer {t_a}"})
    counts = r.json()["questions"][0]["answers"]
    assert counts == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1}
