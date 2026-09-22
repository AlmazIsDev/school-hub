from conftest import ensure_school
from conftest import ensure_school
import json

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from app.core import redis as core_redis
from app.bot import pulse_bot
from app.modules.users.models import School, SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, *keys):
        n = 0
        for k in keys:
            if self.data.pop(k, None) is not None:
                n += 1
        return n

    async def exists(self, key):
        return 1 if key in self.data else 0


class FakeVK:
    def __init__(self):
        self.calls: list[dict] = []

    async def call(self, method, **params):
        self.calls.append({"method": method, **params})


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[School, User, SchoolClass, Poll, PollAnswer])
    yield


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(core_redis, "get_redis", lambda: fr)
    monkeypatch.setattr(pulse_bot, "_r", lambda: fr)
    return fr


@pytest_asyncio.fixture
async def vk():
    return FakeVK()


async def _mk_poll(class_id: str, questions: list[dict], status: str = "active") -> Poll:
    poll = Poll(school_id=await ensure_school(), teacher_id="t", class_id=class_id, title="Опрос", topic="Тема",
                status=status, questions=[{"text": q["text"], "type": q["type"]} for q in questions])
    await poll.insert()
    return poll


async def _mk_student(vk_id: int | None = None, class_id: str | None = None) -> User:
    u = User(school_id=await ensure_school(), login=f"s{vk_id}", password_hash="x", full_name="У",
             role="student", class_id=class_id, vk_id=vk_id)
    await u.insert()
    return u


def _btn_payload(vk_call: dict) -> dict:
    return json.loads(vk_call["keyboard"])["buttons"][0][0]["action"]["payload"]


async def test_published_sends_to_students_with_vk_id(db, fake_redis, vk):
    cid = str((await _insert_class()).id)
    poll = await _mk_poll(cid, [{"text": "Как дела?", "type": "scale1_5"}])
    await _mk_student(vk_id=100, class_id=cid)
    await _mk_student(vk_id=None, class_id=cid)      # без vk_id — пропускаем
    await _mk_student(vk_id=200, class_id="other")   # другой класс — пропускаем

    await pulse_bot.on_published({"poll_id": str(poll.id)}, vk)

    assert [c["peer_id"] for c in vk.calls] == [100]
    msg = vk.calls[0]["message"]
    assert "Как дела?" in msg
    kb = json.loads(vk.calls[0]["keyboard"])
    assert kb["one_time"] is True
    assert [b["action"]["label"] for row in kb["buttons"] for b in row] == \
        ["1", "2", "3", "4", "5"]


async def _insert_class() -> SchoolClass:
    c = SchoolClass(school_id=await ensure_school(), grade=9, letter="А")
    await c.insert()
    return c


async def test_poll_command_starts_single_pending(db, fake_redis, vk):
    cid = str((await _insert_class()).id)
    await _mk_student(vk_id=100, class_id=cid)
    await _mk_poll(cid, [{"text": "Как дела?", "type": "scale1_5"}])

    await pulse_bot.handle_poll_command({"vk_user_id": 100, "peer_id": 100}, vk)

    # единственный незотвеченный опрос стартует сразу, с первого вопроса
    assert any("Вопрос 1/1" in c["message"] for c in vk.calls if "message" in c)


async def test_poll_command_lists_many(db, fake_redis, vk):
    cid = str((await _insert_class()).id)
    await _mk_student(vk_id=100, class_id=cid)
    await _mk_poll(cid, [{"text": "q", "type": "scale1_5"}])
    poll2 = await _mk_poll(cid, [{"text": "q", "type": "scale1_5"}])
    poll2.title = "Второй"
    await poll2.save()

    await pulse_bot.handle_poll_command({"vk_user_id": 100, "peer_id": 100}, vk)

    listing = [c["message"] for c in vk.calls if "message" in c][0]
    assert "Активные опросы" in listing and "Второй" in listing


async def test_poll_command_all_answered(db, fake_redis, vk):
    cid = str((await _insert_class()).id)
    await _mk_student(vk_id=100, class_id=cid)
    poll = await _mk_poll(cid, [{"text": "q", "type": "scale1_5"}])
    fake_redis.data[f"answered:{poll.id}:100"] = "1"

    await pulse_bot.handle_poll_command({"vk_user_id": 100, "peer_id": 100}, vk)

    assert any("уже ответил" in c["message"] for c in vk.calls if "message" in c)


async def test_scale_flow_two_questions_and_finish(db, fake_redis, vk):
    c = await _insert_class()
    cid = str(c.id)
    poll = await _mk_poll(cid, [
        {"text": "Шкала?", "type": "scale1_5"},
        {"text": "Что улучшить?", "type": "free_text"},
    ])
    await _mk_student(vk_id=100, class_id=cid)
    await pulse_bot.on_published({"poll_id": str(poll.id)}, vk)

    # жмём "4" на первом вопросе: payload из клавиатуры (вторая строка, кнопка "4")
    kb = json.loads(vk.calls[0]["keyboard"])
    btn4 = kb["buttons"][1][0]
    assert btn4["action"]["label"] == "4"
    payload = btn4["action"]["payload"]
    assert json.loads(payload) == {"poll": str(poll.id), "q": 0, "v": "4"}
    vk.calls.clear()
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "4"}, vk)
    answers = await PollAnswer.find_all().to_list()
    assert [(a.question_idx, a.value) for a in answers] == [(0, "4")]
    assert "Что улучшить?" in vk.calls[0]["message"]
    assert "keyboard" not in vk.calls[0]  # free_text — без клавиатуры

    # текстовый ответ на второй вопрос
    vk.calls.clear()
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "text": "Больше переменок"}, vk)
    answers = await PollAnswer.find_all().to_list()
    assert len(answers) == 2 and answers[1].value == "Больше переменок"
    assert pulse_bot.THANKS in vk.calls[0]["message"]
    assert "pollstate:100" not in fake_redis.data


async def test_dedup_second_answer_rejected(db, fake_redis, vk):
    c = await _insert_class()
    poll = await _mk_poll(str(c.id), [{"text": "Шкала?", "type": "scale1_5"}])
    await _mk_student(vk_id=100, class_id=str(c.id))
    await pulse_bot.on_published({"poll_id": str(poll.id)}, vk)

    payload = _btn_payload(vk.calls[0])
    vk.calls.clear()
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "5"}, vk)
    assert len(await PollAnswer.find_all().to_list()) == 1

    # state после первого ответа удалён; повторное нажатие — «уже ответили»
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "5"}, vk)
    assert len(await PollAnswer.find_all().to_list()) == 1
    assert any(pulse_bot.ALREADY in c2["message"] for c2 in vk.calls)


async def test_text_without_state_ignored(db, fake_redis, vk):
    vk.calls.clear()
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "text": "просто текст"}, vk)
    assert vk.calls == []


async def test_insert_failure_rolls_back_dedup_and_state(db, fake_redis, vk, monkeypatch):
    c = await _insert_class()
    poll = await _mk_poll(str(c.id), [{"text": "Шкала?", "type": "scale1_5"}])
    await _mk_student(vk_id=100, class_id=str(c.id))
    await pulse_bot.on_published({"poll_id": str(poll.id)}, vk)
    payload = _btn_payload(vk.calls[0])

    class Boom:
        def __init__(self, **kw):
            pass

        async def insert(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(pulse_bot, "PollAnswer", Boom)
    vk.calls.clear()
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "5"}, vk)
    # дедуп и state откатлены — юзер не заблокирован, может повторить
    assert "answered:%s:100" % poll.id not in fake_redis.data
    assert "pollstate:100" not in fake_redis.data
    assert any("Ошибка, попробуйте ещё раз" in c2["message"] for c2 in vk.calls)


async def test_stale_button_ignored(db, fake_redis, vk):
    c = await _insert_class()
    poll = await _mk_poll(str(c.id), [
        {"text": "Шкала?", "type": "scale1_5"},
        {"text": "Текст?", "type": "free_text"},
    ])
    await _mk_student(vk_id=100, class_id=str(c.id))
    await pulse_bot.on_published({"poll_id": str(poll.id)}, vk)
    payload = _btn_payload(vk.calls[0])  # q=0
    # отвечаем на q0, state переехал на idx=1
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "4"}, vk)
    vk.calls.clear()
    # повторное нажатие кнопки q0 при state idx=1 — молча, без ответа и записи
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "4"}, vk)
    assert vk.calls == []
    assert len(await PollAnswer.find_all().to_list()) == 1


async def test_catch_up_unnotified(db, fake_redis, vk):
    c = await _insert_class()
    poll = await _mk_poll(str(c.id), [{"text": "Шкала?", "type": "scale1_5"}])
    await _mk_student(vk_id=100, class_id=str(c.id))

    await pulse_bot.catch_up_unnotified(vk)
    assert [c2["peer_id"] for c2 in vk.calls] == [100]

    fresh = await Poll.get(poll.id)
    assert fresh.notified is True
    # повторный вызов не рассылает второй раз
    vk.calls.clear()
    await pulse_bot.catch_up_unnotified(vk)
    assert vk.calls == []


async def test_poll_closed_midway(db, fake_redis, vk):
    c = await _insert_class()
    poll = await _mk_poll(str(c.id), [{"text": "Шкала?", "type": "scale1_5"}])
    await _mk_student(vk_id=100, class_id=str(c.id))
    await pulse_bot.on_published({"poll_id": str(poll.id)}, vk)
    poll.status = "closed"
    await poll.save()

    payload = _btn_payload(vk.calls[0])
    vk.calls.clear()
    await pulse_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                    "payload": payload, "text": "5"}, vk)
    assert any(pulse_bot.CLOSED in c2["message"] for c2 in vk.calls)
    assert len(await PollAnswer.find_all().to_list()) == 0
    assert "pollstate:100" not in fake_redis.data
