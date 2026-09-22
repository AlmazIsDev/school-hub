from conftest import ensure_school
import json
from datetime import datetime, timezone

import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from app.bot import builder_bot
from app.core import redis as core_redis
from app.modules.builder.models import Quest, QuestRun
from app.modules.users.models import School, User

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.published: list[str] = []

    async def set(self, key, value, ex=None):
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self.data:
                del self.data[k]
                n += 1
        return n

    async def publish(self, channel, message):
        self.published.append((channel, message))


class FakeVK:
    def __init__(self):
        self.calls: list[dict] = []

    async def call(self, method, **params):
        self.calls.append({"method": method, **params})

    def buttons(self, i=0):
        kb = json.loads(self.calls[i]["keyboard"])
        return [(b["action"]["label"], json.loads(b["action"]["payload"]))
                for row in kb["buttons"] for b in row]


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[School, User, Quest, QuestRun])
    yield


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(core_redis, "get_redis", lambda: fr)
    monkeypatch.setattr(builder_bot, "_r", lambda: fr)
    return fr


@pytest_asyncio.fixture
async def vk():
    return FakeVK()


async def _mk_student(vk_id=100, class_id="c1") -> User:
    u = User(school_id=await ensure_school(), login=f"s{vk_id}", password_hash="x", full_name="У",
             role="student", vk_id=vk_id, class_id=class_id)
    await u.insert()
    return u


LINEAR = {"blocks": [
    {"id": "q1", "type": "question", "text": "Столица Франции?",
     "options": ["Париж", "Лондон"], "next": "h1"},
    {"id": "h1", "type": "hint", "text": "Молодец, дальше!", "next": "e1"},
    {"id": "e1", "type": "end", "score": 10},
]}

BRANCHY = {"blocks": [
    {"id": "q1", "type": "question", "text": "2+2?",
     "options": ["4", "5"], "next": "br"},
    {"id": "br", "type": "branch", "condition": {"answer": "4"},
     "then": "h_ok", "else": "h_no"},
    {"id": "h_ok", "type": "hint", "text": "Верно!", "next": "e_ok"},
    {"id": "h_no", "type": "hint", "text": "Неверно.", "next": "e_no"},
    {"id": "e_ok", "type": "end", "score": 5},
    {"id": "e_no", "type": "end", "score": 0},
]}


async def _mk_quest(title="Квиз", structure=LINEAR, status="published",
                    class_id="c1") -> Quest:
    return await Quest(school_id=await ensure_school(), teacher_id="t", class_id=class_id, title=title,
                       structure=structure, status=status).insert()


def _btn(vk, label):
    for call in reversed(vk.calls):
        if "keyboard" not in call:
            continue
        for _label, payload in vk.buttons(vk.calls.index(call)):
            if _label == label:
                return payload
    raise AssertionError(f"no button {label}")


async def test_command_lists_published_quests(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest("Гео-квиз")
    await _mk_quest("Черновик", status="draft")
    await _mk_quest("Чужой класс", class_id="c2")
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    msg = vk.calls[0]["message"]
    assert "1. Гео-квиз" in msg
    assert "Черновик" not in msg and "Чужой класс" not in msg
    state = json.loads(fake_redis.data["queststate:100"])
    assert state["flow"] == "choose" and len(state["ids"]) == 1


async def test_command_no_quests(db, fake_redis, vk):
    await _mk_student()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    assert vk.calls[0]["message"] == builder_bot.NO_QUESTS


async def test_linear_flow(db, fake_redis, vk):
    u = await _mk_student()
    q = await _mk_quest()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)

    # выбор цифрой → первый вопрос с кнопками
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)
    assert vk.calls[1]["message"] == "Столица Франции?"
    assert _btn(vk, "Париж") == {"quest": "ans", "block": "q1", "value": "Париж"}

    # ответ → hint + кнопка «Дальше»
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "Париж"))}, vk)
    assert vk.calls[2]["message"] == "Молодец, дальше!"
    assert _btn(vk, "Дальше") == {"quest": "next", "block": "h1"}

    # дальше → end, run завершён
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "Дальше"))}, vk, now=NOW)
    assert vk.calls[3]["message"] == "Квест завершён! Баллы: 10"
    runs = await QuestRun.find_all().to_list()
    assert len(runs) == 1
    run = runs[0]
    assert run.finished and run.score == 10
    assert run.finished_at.strftime("%Y-%m-%dT%H:%M") == NOW.strftime("%Y-%m-%dT%H:%M")
    assert run.user_id == str(u.id) and run.quest_id == str(q.id)
    assert run.trace == [{"block_id": "q1", "value": "Париж"},
                         {"block_id": "h1", "value": None},
                         {"block_id": "e1", "value": None}]
    assert "queststate:100" not in fake_redis.data
    assert any(json.loads(m)["type"] == "quest.finished" for _, m in fake_redis.published)


async def test_branch_then_and_else(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest("Мат", structure=BRANCHY)
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)

    # ветка then: branch не показывается, сразу hint
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "4"))}, vk)
    assert vk.calls[2]["message"] == "Верно!"
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "Дальше"))}, vk, now=NOW)
    assert vk.calls[3]["message"] == "Квест завершён! Баллы: 5"

    # ветка else: новый ран
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "5"))}, vk)
    assert vk.calls[6]["message"] == "Неверно."
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "Дальше"))}, vk, now=NOW)
    assert "Баллы: 0" in vk.calls[7]["message"]
    runs = await QuestRun.find_all().to_list()
    assert {r.score for r in runs} == {5, 0}


async def test_stop_interrupts(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)

    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "стоп"}, vk)
    assert vk.calls[2]["message"] == builder_bot.INTERRUPTED
    assert "queststate:100" not in fake_redis.data
    run = (await QuestRun.find_all().to_list())[0]
    assert not run.finished and run.trace == []


async def test_choice_bad_digit_silent(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    n = len(vk.calls)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "5"}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "abc"}, vk)
    assert len(vk.calls) == n  # молча


async def test_quest_closed_midway(db, fake_redis, vk):
    await _mk_student()
    q = await _mk_quest()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)

    q.status = "closed"
    await q.save()
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "Париж"))}, vk)
    assert vk.calls[2]["message"] == builder_bot.CLOSED
    assert "queststate:100" not in fake_redis.data
    assert not (await QuestRun.find_all().to_list())[0].finished


async def test_stale_and_broken_payloads_silent(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)
    n = len(vk.calls)
    # чужой payload, битый JSON, ans без state-совпадения, next на question
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps({"poll": "x"})}, vk)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": "{not json"}, vk)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(
            {"quest": "ans", "block": "zz", "value": "Париж"})}, vk)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(
            {"quest": "next", "block": "q1"})}, vk)
    assert len(vk.calls) == n


async def test_double_next_ignored(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest()
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(_btn(vk, "Париж"))}, vk)
    nxt = json.dumps(_btn(vk, "Дальше"))
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": nxt}, vk, now=NOW)  # hint → end
    n = len(vk.calls)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": nxt}, vk, now=NOW)  # дубль
    assert len(vk.calls) == n  # молча, run не изменился
    run = (await QuestRun.find_all().to_list())[0]
    assert run.finished and len(run.trace) == 3  # q1 + h1 + e1


async def test_broken_state_json_silent(db, fake_redis, vk):
    await _mk_student()
    await _mk_quest()
    fake_redis.data["queststate:100"] = "{not json"
    n = len(vk.calls)
    await builder_bot.handle_message(
        {"vk_user_id": 100, "peer_id": 100, "payload": json.dumps(
            {"quest": "ans", "block": "q1", "value": "Париж"})}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "стоп"}, vk)
    assert len(vk.calls) == n
    assert "queststate:100" not in fake_redis.data  # мусорный ключ вычищен


async def test_unbound_user_silent(db, fake_redis, vk):
    await builder_bot.handle_quest({"vk_user_id": 100, "peer_id": 100}, vk)
    assert vk.calls == []
    await builder_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "1"}, vk)
    assert vk.calls == []
