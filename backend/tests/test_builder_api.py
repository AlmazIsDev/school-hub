import pytest
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import SchoolClass, User
from app.modules.builder.models import Quest, QuestRun
from app.modules.builder.quest_structure import QuestStructure, validate_structure

ALL_MODELS = [User, SchoolClass, Quest, QuestRun]


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


async def _mk_user(login: str, role: str, class_id: str | None = None) -> str:
    from app.modules.users.service import create_user
    from app.core.auth import make_tokens
    u, _ = await create_user(login=login, full_name="У", role=role, class_id=class_id)
    return make_tokens(u.id, u.role)["access"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def env(client):
    cls = SchoolClass(grade=9, letter="А")
    await cls.insert()
    other = SchoolClass(grade=9, letter="Б")
    await other.insert()
    return {"class": str(cls.id), "other_class": str(other.id),
            "teacher": await _mk_user("t1", "teacher"),
            "admin": await _mk_user("a1", "admin"),
            "student": await _mk_user("s1", "student", class_id=str(cls.id)),
            "alien_student": await _mk_user("s2", "student", class_id=str(other.id))}


def _blocks(**over):
    blocks = [
        {"id": "q1", "type": "question", "text": "Вопрос", "options": ["а", "б"], "next": "q2"},
        {"id": "q2", "type": "branch", "condition": {"answer": "а"},
         "then": "e1", "else": "h1"},
        {"id": "h1", "type": "hint", "text": "Подсказка", "next": "e1"},
        {"id": "e1", "type": "end", "score": 10},
    ]
    return [b for b in blocks if b["id"] not in over.pop("drop", [])] + over.pop("extra", [])


def _quest_body(env, **kw):
    return {"title": "Квест", "class_id": env["class"],
            "structure": {"blocks": kw.get("blocks", _blocks())}}


def _valid(blocks: list[dict]) -> bool:
    return not validate_structure(QuestStructure(blocks=blocks))


# ---------- валидатор ----------

def test_validator_ok():
    assert _valid(_blocks())


def test_validator_cycle():
    blocks = [
        {"id": "q1", "type": "question", "text": "В", "options": ["а", "б"], "next": "q2"},
        {"id": "q2", "type": "hint", "text": "П", "next": "q1"},
        {"id": "e1", "type": "end", "score": 0},
    ]
    assert not _valid(blocks)  # end недостижим + цикл


def test_validator_unreachable():
    blocks = _blocks(extra=[{"id": "h2", "type": "hint", "text": "П", "next": "e1"}])
    errs = validate_structure(QuestStructure(blocks=blocks))
    assert any("недостижим" in e for e in errs)


def test_validator_bad_next():
    blocks = _blocks()
    blocks[0]["next"] = "nope"
    errs = validate_structure(QuestStructure(blocks=blocks))
    assert any("несуществующий" in e for e in errs)


def test_validator_two_ends_ok():
    # оба end достижимы: branch ведёт в e1 и e2 — легитимный дизайн,
    # разные score по веткам; запрещён только ноль достижимых end
    blocks = [
        {"id": "q1", "type": "question", "text": "В", "options": ["а", "б"], "next": "b2"},
        {"id": "b2", "type": "branch", "condition": {"answer": "а"},
         "then": "e1", "else": "e2"},
        {"id": "e1", "type": "end", "score": 10},
        {"id": "e2", "type": "end", "score": 5},
    ]
    assert _valid(blocks)


def test_validator_then_equals_else():
    blocks = _blocks()
    blocks[1]["then"] = "h1"
    errs = validate_structure(QuestStructure(blocks=blocks))
    assert any("then и else" in e for e in errs)


def test_validator_bad_ids():
    blocks = _blocks()
    blocks[0]["id"] = ""
    errs = validate_structure(QuestStructure(blocks=blocks))
    assert any("пустой id" in e for e in errs)
    blocks = _blocks()
    blocks[1]["id"] = "q1"
    errs = validate_structure(QuestStructure(blocks=blocks))
    assert any("дубли id" in e for e in errs)


# ---------- API ----------

async def test_create_quest_rights_and_class(client, env):
    body = _quest_body(env)
    r = await client.post("/api/builder/quests", json=body, headers=_h(env["student"]))
    assert r.status_code == 403
    r = await client.post("/api/builder/quests", json=body, headers=_h(env["teacher"]))
    assert r.status_code == 200
    r = await client.post("/api/builder/quests",
                          json={**body, "class_id": "0" * 24}, headers=_h(env["teacher"]))
    assert r.status_code == 404


async def test_create_quest_bad_structure_422(client, env):
    blocks = _blocks()
    blocks[0]["next"] = "nope"
    r = await client.post("/api/builder/quests", json=_quest_body(env, blocks=blocks),
                          headers=_h(env["teacher"]))
    assert r.status_code == 422


async def test_list_own_only(client, env):
    await client.post("/api/builder/quests", json=_quest_body(env), headers=_h(env["teacher"]))
    other_teacher = await _mk_user("t2", "teacher")
    await client.post("/api/builder/quests", json=_quest_body(env), headers=_h(other_teacher))
    r = await client.get("/api/builder/quests", headers=_h(env["teacher"]))
    assert len(r.json()) == 1
    r = await client.get("/api/builder/quests", headers=_h(env["admin"]))
    assert len(r.json()) == 2


async def test_publish_close_transitions(client, env):
    qid = (await client.post("/api/builder/quests", json=_quest_body(env),
                             headers=_h(env["teacher"]))).json()["id"]
    # close до publish нельзя
    r = await client.post(f"/api/builder/quests/{qid}/close", headers=_h(env["teacher"]))
    assert r.status_code == 409
    r = await client.post(f"/api/builder/quests/{qid}/publish", headers=_h(env["teacher"]))
    assert r.json()["status"] == "published"
    # повторный publish
    r = await client.post(f"/api/builder/quests/{qid}/publish", headers=_h(env["teacher"]))
    assert r.status_code == 409
    r = await client.post(f"/api/builder/quests/{qid}/close", headers=_h(env["teacher"]))
    assert r.json()["status"] == "closed"
    # повторный close
    r = await client.post(f"/api/builder/quests/{qid}/close", headers=_h(env["teacher"]))
    assert r.status_code == 409


async def test_update_draft_only_and_owner(client, env):
    qid = (await client.post("/api/builder/quests", json=_quest_body(env),
                             headers=_h(env["teacher"]))).json()["id"]
    alien = await _mk_user("t2", "teacher")
    r = await client.put(f"/api/builder/quests/{qid}", json=_quest_body(env),
                         headers=_h(alien))
    assert r.status_code == 403
    r = await client.put(f"/api/builder/quests/{qid}",
                         json={**_quest_body(env), "title": "Новое"},
                         headers=_h(env["teacher"]))
    assert r.status_code == 200
    assert r.json()["title"] == "Новое"
    await client.post(f"/api/builder/quests/{qid}/publish", headers=_h(env["teacher"]))
    r = await client.put(f"/api/builder/quests/{qid}",
                         json={**_quest_body(env), "title": "Ещё"},
                         headers=_h(env["teacher"]))
    assert r.status_code == 409
    # админ может редактировать чужой draft
    q2 = (await client.post("/api/builder/quests", json=_quest_body(env),
                            headers=_h(env["teacher"]))).json()["id"]
    r = await client.put(f"/api/builder/quests/{q2}",
                         json={**_quest_body(env), "title": "Админ"},
                         headers=_h(env["admin"]))
    assert r.status_code == 200


async def test_play_strips_score_and_condition(client, env):
    qid = (await client.post("/api/builder/quests", json=_quest_body(env),
                             headers=_h(env["teacher"]))).json()["id"]
    await client.post(f"/api/builder/quests/{qid}/publish", headers=_h(env["teacher"]))
    r = await client.get(f"/api/builder/quests/{qid}/play", headers=_h(env["student"]))
    assert r.status_code == 200
    blocks = r.json()["blocks"]
    branch = next(b for b in blocks if b["type"] == "branch")
    assert "condition" not in branch
    end = next(b for b in blocks if b["type"] == "end")
    assert "score" not in end


async def test_play_other_class_403(client, env):
    qid = (await client.post("/api/builder/quests", json=_quest_body(env),
                             headers=_h(env["teacher"]))).json()["id"]
    await client.post(f"/api/builder/quests/{qid}/publish", headers=_h(env["teacher"]))
    r = await client.get(f"/api/builder/quests/{qid}/play", headers=_h(env["alien_student"]))
    assert r.status_code == 403
    # черновик даже своему классу нельзя
    draft = (await client.post("/api/builder/quests", json=_quest_body(env),
                               headers=_h(env["teacher"]))).json()["id"]
    r = await client.get(f"/api/builder/quests/{draft}/play", headers=_h(env["student"]))
    assert r.status_code == 409


def test_diamond_no_false_positive():
    # ромб q1 -> a -> e, q1 -> b -> e: merge в один end, цикла нет
    blocks = [
        {"id": "q1", "type": "question", "text": "?", "options": ["1", "2"], "next": "a"},
        {"id": "a", "type": "hint", "text": "a", "next": "e"},
        {"id": "b", "type": "hint", "text": "b", "next": "e"},
        {"id": "e", "type": "end", "score": 5},
    ]
    # q1.next указывает на a; нужен второй переход q1->b — сделаем через branch
    blocks[0] = {"id": "q1", "type": "branch", "condition": {"answer": "1"},
                 "then": "a", "else": "b"}
    assert validate_structure(QuestStructure(blocks=blocks)) == []


async def test_stats_funnel(client, env):
    qid = (await client.post("/api/builder/quests", json=_quest_body(env),
                             headers=_h(env["teacher"]))).json()["id"]
    from app.modules.builder.models import QuestRun
    from datetime import datetime, timezone
    # прогон 1: дошёл до конца (q1, q2, e1)
    await QuestRun(quest_id=qid, user_id="s1", finished=True, score=10,
                   trace=[{"block_id": "q1", "value": "а"},
                          {"block_id": "q2", "value": "а"},
                          {"block_id": "e1", "value": None}],
                   started_at=datetime.now(timezone.utc),
                   finished_at=datetime.now(timezone.utc)).insert()
    # прогон 2: бросил после q1
    await QuestRun(quest_id=qid, user_id="s2", finished=False, score=0,
                   trace=[{"block_id": "q1", "value": "б"}],
                   started_at=datetime.now(timezone.utc)).insert()

    r = await client.get(f"/api/builder/quests/{qid}/stats", headers=_h(env["teacher"]))
    assert r.status_code == 200
    data = r.json()
    assert data["runs"] == 2
    assert data["finished"] == 1
    assert data["avg_score"] == 10
    funnel = {f["block_id"]: f["reached"] for f in data["funnel"]}
    assert funnel == {"q1": 2, "q2": 1, "h1": 0, "e1": 1}

    # чужому учителю нельзя, студенту нельзя
    r = await client.get(f"/api/builder/quests/{qid}/stats",
                         headers=_h(await _mk_user("t2", "teacher")))
    assert r.status_code == 403
    r = await client.get(f"/api/builder/quests/{qid}/stats", headers=_h(env["student"]))
    assert r.status_code == 403
