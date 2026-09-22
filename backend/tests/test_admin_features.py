from conftest import ensure_school
"""Расширенная админка: CRUD юзеров/классов и прямое управление БД."""
import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from httpx import ASGITransport, AsyncClient

import app.core.db as core_db
import app.modules.admin.router as admin_router
from app.main import create_app
from app.modules.users.models import School, SchoolClass, User


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    from beanie import init_beanie
    await init_beanie(client.get_database("test"), document_models=[School, User, SchoolClass])
    yield client


@pytest_asyncio.fixture
async def client(db, monkeypatch):
    # admin/db-роутер работает поверх того же mongomock-клиента
    class _FakeClient:
        def __init__(self, database):
            self._db = database
        def get_database(self, name=None):
            return self._db
    fake = _FakeClient(db.get_database("test"))
    monkeypatch.setattr(core_db, "get_motor_client", lambda: fake)
    monkeypatch.setattr(admin_router, "get_motor_client", lambda: fake)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _admin(client) -> dict:
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="adm", full_name="Админ", role="admin")
    r = await client.post("/api/auth/login", json={"school_code": "s1", "login": "adm", "password": tmp})
    return {"Authorization": f"Bearer {r.json()['access']}"}


async def _student(client, login="s1", class_id=None) -> str:
    from app.modules.users.service import create_user
    u, _ = await create_user(school_id=await ensure_school(), login=login, full_name="Ученик", role="student", class_id=class_id)
    return str(u.id)


async def _h(client) -> dict:
    return await _admin(client)


# ---------- CRUD пользователей ----------

async def test_patch_user(client, db):
    h = await _h(client)
    uid = await _student(client)
    r = await client.patch(f"/api/users/{uid}", json={"full_name": "Новый", "role": "teacher"},
                           headers=h)
    assert r.status_code == 200
    u = await User.get(uid)
    assert u.full_name == "Новый" and u.role == "teacher"


async def test_reset_password_makes_temp(client, db):
    h = await _h(client)
    uid = await _student(client)
    r = await client.post(f"/api/users/{uid}/reset-password", headers=h)
    assert r.status_code == 200 and "temp_password" in r.json()
    # временный пароль работает
    r = await client.post("/api/auth/login",
                          json={"school_code": "s1", "login": "s1", "password": r.json()["temp_password"]})
    assert r.status_code == 200 and r.json()["must_change_password"] is True


async def test_delete_user_and_self_guard(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="adm", full_name="Админ", role="admin")
    tok = (await client.post("/api/auth/login", json={"school_code": "s1", "login": "adm", "password": tmp})).json()
    h = {"Authorization": f"Bearer {tok['access']}"}
    me = await User.find_one(User.login == "adm")
    r = await client.delete(f"/api/users/{me.id}", headers=h)
    assert r.status_code == 409  # сам себя
    uid = await _student(client)
    r = await client.delete(f"/api/users/{uid}", headers=h)
    assert r.status_code == 200
    assert await User.get(uid) is None


async def test_admin_unlink_vk(client, db):
    h = await _h(client)
    uid = await _student(client)
    u = await User.get(uid)
    u.vk_id = 777
    await u.save()
    r = await client.delete(f"/api/users/{uid}/vk", headers=h)
    assert r.status_code == 200
    assert (await User.get(uid)).vk_id is None


async def test_delete_class_guard(client, db):
    h = await _h(client)
    cls = SchoolClass(school_id=await ensure_school(), grade=5, letter="А")
    await cls.insert()
    uid = await _student(client, class_id=str(cls.id))
    r = await client.delete(f"/api/classes/{cls.id}", headers=h)
    assert r.status_code == 409  # в классе есть ученик
    await (await User.get(uid)).delete()
    r = await client.delete(f"/api/classes/{cls.id}", headers=h)
    assert r.status_code == 200


async def test_admin_only(client, db):
    from app.modules.users.service import create_user
    _, tmp = await create_user(school_id=await ensure_school(), login="t1", full_name="Учитель", role="teacher")
    h = {"Authorization": f"Bearer {(await client.post('/api/auth/login', json={'school_code': 's1', 'login': 't1', 'password': tmp})).json()['access']}"}
    r = await client.get("/api/admin/db/collections", headers=h)
    assert r.status_code == 403


# ---------- прямое управление БД ----------

async def test_db_collections_and_docs(client, db):
    h = await _h(client)
    await db.get_database("test")["school_classes"].insert_one({"grade": 3, "letter": "В"})
    r = await client.get("/api/admin/db/collections", headers=h)
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert "school_classes" in names
    r = await client.get("/api/admin/db/school_classes/docs", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    doc = next(d for d in body["items"] if d.get("grade") == 3)
    doc_id = doc["_id"]["$oid"]

    # поиск по полю
    r = await client.get("/api/admin/db/school_classes/docs?q=grade:%203", headers=h)
    assert any(d.get("grade") == 3 for d in r.json()["items"])

    # правка
    doc["grade"] = 4
    r = await client.put(f"/api/admin/db/school_classes/{doc_id}", json=doc, headers=h)
    assert r.status_code == 200
    updated = await db.get_database("test")["school_classes"].find_one({"grade": 4})
    assert updated is not None

    # удаление
    r = await client.delete(f"/api/admin/db/school_classes/{doc_id}", headers=h)
    assert r.status_code == 200
    assert await db.get_database("test")["school_classes"].find_one({"grade": 4}) is None


async def test_db_system_collections_denied(client, db):
    h = await _h(client)
    r = await client.get("/api/admin/db/system.views/docs", headers=h)
    assert r.status_code == 404
    r = await client.get("/api/admin/db/fs.chunks/docs", headers=h)
    assert r.status_code == 404


async def test_db_create_doc(client, db):
    h = await _h(client)
    r = await client.post("/api/admin/db/school_classes",
                          json={"grade": 6, "letter": "Г"}, headers=h)
    assert r.status_code == 200
    assert await db.get_database("test")["school_classes"].find_one({"grade": 6}) is not None
