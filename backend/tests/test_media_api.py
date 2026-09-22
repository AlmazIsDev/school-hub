from conftest import ensure_school
import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import School, SchoolClass, User
from app.modules.media.models import Post, PostIdea

ALL_MODELS = [School, User, SchoolClass, Post, PostIdea]


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


async def _mk_user(login: str, role: str) -> str:
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    u, _ = await create_user(school_id=await ensure_school(), login=login, full_name="У", role=role)
    return make_tokens(u.id, u.role, u.school_id)["access"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def tokens(db):
    return {"teacher": await _mk_user("t1", "teacher"),
            "admin": await _mk_user("a1", "admin"),
            "student": await _mk_user("s1", "student")}


async def _mk_post(client, tokens) -> str:
    r = await client.post("/api/media/posts", json={"title": "Пост", "body": "Текст"},
                          headers=_h(tokens["teacher"]))
    return r.json()["id"]


# ---------- posts: права ----------

async def test_post_rights(client, tokens):
    # student не создаёт посты и не патчит
    r = await client.post("/api/media/posts", json={"title": "T", "body": "B"},
                          headers=_h(tokens["student"]))
    assert r.status_code == 403
    r = await client.post("/api/media/posts", json={"title": "Пост", "body": "Текст"},
                          headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    assert r.json()["status"] == "idea"
    post_id = r.json()["id"]

    r = await client.patch(f"/api/media/posts/{post_id}", json={"title": "X"},
                           headers=_h(tokens["student"]))
    assert r.status_code == 403

    # учитель и админ патчат
    for who in ("teacher", "admin"):
        r = await client.patch(f"/api/media/posts/{post_id}", json={"title": f"T-{who}"},
                               headers=_h(tokens[who]))
        assert r.status_code == 200


async def test_post_validation(client, tokens):
    r = await client.post("/api/media/posts", json={"title": "", "body": "B"},
                          headers=_h(tokens["teacher"]))
    assert r.status_code == 422
    r = await client.post("/api/media/posts", json={"title": "x" * 201, "body": "B"},
                          headers=_h(tokens["teacher"]))
    assert r.status_code == 422


# ---------- posts: переходы статуса ----------

async def test_status_chain_forward(client, tokens):
    post_id = await _mk_post(client, tokens)
    for expected in ("in_progress", "review", "published"):
        r = await client.patch(f"/api/media/posts/{post_id}", json={"status": expected},
                               headers=_h(tokens["teacher"]))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == expected


async def test_status_backward_409(client, tokens):
    post_id = await _mk_post(client, tokens)
    r = await client.patch(f"/api/media/posts/{post_id}", json={"status": "in_progress"},
                           headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    r = await client.patch(f"/api/media/posts/{post_id}", json={"status": "idea"},
                           headers=_h(tokens["teacher"]))
    assert r.status_code == 409


async def test_status_skip_409(client, tokens):
    post_id = await _mk_post(client, tokens)
    # через один
    r = await client.patch(f"/api/media/posts/{post_id}", json={"status": "review"},
                           headers=_h(tokens["teacher"]))
    assert r.status_code == 409
    # и сразу в published
    r = await client.patch(f"/api/media/posts/{post_id}", json={"status": "published"},
                           headers=_h(tokens["teacher"]))
    assert r.status_code == 409


async def test_patch_other_fields(client, tokens):
    post_id = await _mk_post(client, tokens)
    r = await client.patch(f"/api/media/posts/{post_id}",
                           json={"assignee_id": "abc", "publish_at": "2026-10-01T12:00:00Z"},
                           headers=_h(tokens["admin"]))
    assert r.status_code == 200
    data = r.json()
    assert data["assignee_id"] == "abc"
    assert data["publish_at"].startswith("2026-10-01")
    assert data["status"] == "idea"


# ---------- ideas ----------

async def test_idea_rights_and_accept(client, tokens):
    # ученик предлагает тему
    r = await client.post("/api/media/ideas", json={"text": "Сделать репортаж о субботнике"},
                          headers=_h(tokens["student"]))
    assert r.status_code == 200
    assert r.json()["status"] == "new"
    idea_id = r.json()["id"]

    # список идей — только teacher/admin
    r = await client.get("/api/media/ideas", headers=_h(tokens["student"]))
    assert r.status_code == 403
    r = await client.get("/api/media/ideas?status=new", headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    assert [i["id"] for i in r.json()] == [idea_id]

    # accept создаёт пост
    r = await client.post(f"/api/media/ideas/{idea_id}/accept", headers=_h(tokens["admin"]))
    assert r.status_code == 200
    data = r.json()
    assert data["idea"]["status"] == "accepted"
    assert data["post"]["status"] == "idea"
    assert data["post"]["title"] == "Сделать репортаж о субботнике"
    assert data["post"]["body"] == "Сделать репортаж о субботнике"

    # повторный accept/reject — 409
    r = await client.post(f"/api/media/ideas/{idea_id}/accept", headers=_h(tokens["admin"]))
    assert r.status_code == 409
    r = await client.post(f"/api/media/ideas/{idea_id}/reject", headers=_h(tokens["admin"]))
    assert r.status_code == 409


async def test_idea_reject(client, tokens):
    r = await client.post("/api/media/ideas", json={"text": "Плохая идея"},
                          headers=_h(tokens["student"]))
    idea_id = r.json()["id"]
    r = await client.post(f"/api/media/ideas/{idea_id}/reject", headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    # пост не создался
    r = await client.get("/api/media/posts", headers=_h(tokens["teacher"]))
    assert r.json() == []


async def test_idea_accept_long_text_truncated_title(client, tokens):
    text = "А" * 100
    r = await client.post("/api/media/ideas", json={"text": text},
                          headers=_h(tokens["student"]))
    idea_id = r.json()["id"]
    r = await client.post(f"/api/media/ideas/{idea_id}/accept", headers=_h(tokens["teacher"]))
    assert r.json()["post"]["title"] == "А" * 60
    assert r.json()["post"]["body"] == text


async def test_student_sees_only_published(client, db):
    st = _h(await _mk_user("m1", "student"))
    th = _h(await _mk_user("m2", "teacher"))
    # идея → accept → пост в статусе idea (не published)
    iid = (await client.post("/api/media/ideas", json={"text": "Скрытая тема"}, headers=st)).json()["id"]
    pid = (await client.post(f"/api/media/ideas/{iid}/accept", headers=th)).json()["post"]["id"]
    r = await client.get("/api/media/posts", headers=st)
    assert all(p["id"] != pid for p in r.json())
    # переводим в published — теперь виден
    for s in ("in_progress", "review", "published"):
        assert (await client.patch(f"/api/media/posts/{pid}", json={"status": s}, headers=th)).status_code == 200
    r = await client.get("/api/media/posts", headers=st)
    assert any(p["id"] == pid for p in r.json())
