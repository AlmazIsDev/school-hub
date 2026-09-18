import json
from datetime import datetime, timezone

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from app.core import redis as core_redis
from app.bot import bridge_bot
from app.bot.dispatcher import Dispatcher
from app.bot.handlers import register
from app.modules.users.models import SchoolClass, User
from app.modules.bridge.models import (
    Ban, HelpRequest, HelperTopic, PairMessage, Report, StopWord, TutorPair,
)
from app.modules.pulse.models import Poll, PollAnswer


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.published: list[str] = []

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

    async def publish(self, channel, message):
        self.published.append(message)


class FakeVK:
    def __init__(self):
        self.calls: list[dict] = []

    async def call(self, method, **params):
        self.calls.append({"method": method, **params})


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(
        client.get_database("test"),
        document_models=[SchoolClass, User, Poll, PollAnswer, HelperTopic,
                         HelpRequest, TutorPair, PairMessage, Report, Ban, StopWord],
    )
    yield


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(core_redis, "get_redis", lambda: fr)
    monkeypatch.setattr(bridge_bot, "_r", lambda: fr)
    return fr


@pytest_asyncio.fixture
async def vk():
    return FakeVK()


async def _mk_user(vk_id: int, name: str = "У") -> User:
    u = User(login=f"u{vk_id}", password_hash="x", full_name=name,
             role="student", vk_id=vk_id)
    await u.insert()
    return u


def _calls_to(vk, peer_id):
    return [c for c in vk.calls if c["peer_id"] == peer_id]


def _btn_payload(call: dict) -> str:
    return json.loads(call["keyboard"])["buttons"][0][0]["action"]["payload"]


async def test_become_helper_state_machine(db, fake_redis, vk):
    u = await _mk_user(100)
    await bridge_bot.start_become_helper({"vk_user_id": 100, "peer_id": 100}, vk)
    assert json.loads(fake_redis.data["bridgestate:100"])["flow"] == "become_helper"

    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "алгебра"}, vk)
    state = json.loads(fake_redis.data["bridgestate:100"])
    assert state == {"flow": "become_helper", "step": "confirm", "topic": "алгебра"}
    assert "алгебра" in vk.calls[-1]["message"]

    payload = _btn_payload(vk.calls[-1])
    vk.calls.clear()
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                     "payload": payload, "text": "Да"}, vk)
    topics = await HelperTopic.find_all().to_list()
    assert [(t.user_id, t.topic) for t in topics] == [(str(u.id), "алгебра")]
    assert "bridgestate:100" not in fake_redis.data

    # повторная регистрация той же темы — дубликат не создаётся
    await bridge_bot.start_become_helper({"vk_user_id": 100, "peer_id": 100}, vk)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "алгебра"}, vk)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                     "payload": payload, "text": "Да"}, vk)
    assert len(await HelperTopic.find_all().to_list()) == 1


async def test_become_helper_confirm_no(db, fake_redis, vk):
    await _mk_user(100)
    await bridge_bot.start_become_helper({"vk_user_id": 100, "peer_id": 100}, vk)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "геометрия"}, vk)
    kb = json.loads(vk.calls[-1]["keyboard"])
    no_payload = kb["buttons"][0][1]["action"]["payload"]  # кнопка «Нет»
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                     "payload": no_payload, "text": "Нет"}, vk)
    assert len(await HelperTopic.find_all().to_list()) == 0
    assert "bridgestate:100" not in fake_redis.data


async def test_need_help_matched(db, fake_redis, vk):
    helper = await _mk_user(100, "Помощник")
    seeker = await _mk_user(200, "Заявитель")
    await HelperTopic(user_id=str(helper.id), topic="алгебра").insert()

    await bridge_bot.start_need_help({"vk_user_id": 200, "peer_id": 200}, vk)
    await bridge_bot.handle_message({"vk_user_id": 200, "peer_id": 200, "text": "алгебра"}, vk)

    pairs = await TutorPair.find_all().to_list()
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.helper_id == str(helper.id) and pair.seeker_id == str(seeker.id)
    assert pair.status == "active" and pair.chat_key
    assert len(await HelpRequest.find_all().to_list()) == 1
    req = (await HelpRequest.find_all().to_list())[0]
    assert req.status == "paired" and pair.request_id == str(req.id)
    # приветствие обоим с chat_key
    assert any(pair.chat_key in c["message"] for c in _calls_to(vk, 100))
    assert any(pair.chat_key in c["message"] for c in _calls_to(vk, 200))
    assert any(p["type"] == "bridge.pair_created" for p in
               (json.loads(x) for x in fake_redis.published))


async def test_need_help_no_helper_waiting_then_try_match(db, fake_redis, vk):
    seeker = await _mk_user(200)
    await bridge_bot.start_need_help({"vk_user_id": 200, "peer_id": 200}, vk)
    await bridge_bot.handle_message({"vk_user_id": 200, "peer_id": 200, "text": "химия"}, vk)

    assert len(await TutorPair.find_all().to_list()) == 0
    req = (await HelpRequest.find_all().to_list())[0]
    assert req.status == "waiting"
    assert any("Пока никого нет" in c["message"] for c in _calls_to(vk, 200))

    # регистрируется помощник — try_match подбирает waiting-заявку
    helper = await _mk_user(100, "Помощник")
    await bridge_bot.start_become_helper({"vk_user_id": 100, "peer_id": 100}, vk)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "химия"}, vk)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100,
                                     "payload": _btn_payload(vk.calls[-1]), "text": "Да"}, vk)

    req = await HelpRequest.get(req.id)
    assert req.status == "paired"
    pair = (await TutorPair.find_all().to_list())[0]
    assert pair.helper_id == str(helper.id) and pair.seeker_id == str(seeker.id)
    # и заявителю, и помощнику ушло уведомление
    assert any("Нашёлся помощник" in c["message"] for c in _calls_to(vk, 200))
    assert any("Новая пара" in c["message"] for c in _calls_to(vk, 100))


async def test_match_excludes_self_banned_and_loads(db, fake_redis, vk):
    await _mk_user(100, "Сам")        # сам заявитель — исключён, хоть и помощник
    banned = await _mk_user(300, "Бан")
    await HelperTopic(user_id=str((await User.find_one(User.vk_id == 100)).id), topic="физика").insert()
    await HelperTopic(user_id=str(banned.id), topic="физика").insert()
    await Ban(user_id=str(banned.id), reason="тест").insert()  # until=None — навсегда
    free = await _mk_user(400, "Свободный")
    loaded = await _mk_user(500, "Загруженный")
    await HelperTopic(user_id=str(free.id), topic="физика").insert()
    await HelperTopic(user_id=str(loaded.id), topic="физика").insert()
    other = await _mk_user(600, "Другой")
    # у «Загруженного» уже есть активная пара
    await TutorPair(helper_id=str(loaded.id), seeker_id=str(other.id),
                    chat_key="x").insert()

    await bridge_bot.start_need_help({"vk_user_id": 100, "peer_id": 100}, vk)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "физика"}, vk)

    pair = (await TutorPair.find_all().to_list())[-1]
    assert pair.helper_id == str(free.id)
    assert any("Вы заблокированы" not in c["message"] for c in _calls_to(vk, 100))


async def test_banned_cannot_start_flows(db, fake_redis, vk):
    u = await _mk_user(100)
    until_ban = datetime(2999, 1, 1, tzinfo=timezone.utc)
    await Ban(user_id=str(u.id), until=until_ban, reason="тест").insert()
    await bridge_bot.start_become_helper({"vk_user_id": 100, "peer_id": 100}, vk)
    await bridge_bot.start_need_help({"vk_user_id": 100, "peer_id": 100}, vk)
    assert len(await HelperTopic.find_all().to_list()) == 0
    assert len(await HelpRequest.find_all().to_list()) == 0
    msgs = [c["message"] for c in _calls_to(vk, 100)]
    assert all("Вы заблокированы до" in m for m in msgs)


async def test_forward_clean_and_stopword(db, fake_redis, vk):
    helper = await _mk_user(100, "Помощник")
    seeker = await _mk_user(200, "Заявитель")
    pair = await TutorPair(helper_id=str(helper.id), seeker_id=str(seeker.id),
                           chat_key="ck").insert()
    await StopWord(word="дурак").insert()

    # чистое сообщение доставлено и сохранено
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "привет"}, vk)
    msgs = await PairMessage.find_all().to_list()
    assert [(m.pair_id, m.sender_id, m.text) for m in msgs] == [(str(pair.id), str(helper.id), "привет")]
    assert _calls_to(vk, 200)[0]["message"] == "Собеседник: привет"
    assert len(await Report.find_all().to_list()) == 0

    # стоп-слово: не доставлено, автору предупреждение, авто-репорт с message_id
    vk.calls.clear()
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "ты дурак"}, vk)
    assert len(await PairMessage.find_all().to_list()) == 2  # сохранено для модерации
    assert _calls_to(vk, 200) == []
    assert any("не доставлено" in c["message"] for c in _calls_to(vk, 100))
    report = (await Report.find_all().to_list())[0]
    assert report.reported_user_id == str(helper.id)
    assert report.status == "open" and "авто" in report.reason and report.message_id


async def test_finish_pair_and_rates(db, fake_redis, vk):
    helper = await _mk_user(100, "Помощник")
    seeker = await _mk_user(200, "Заявитель")
    req = await HelpRequest(user_id=str(seeker.id), topic="алгебра", status="paired").insert()
    pair = await TutorPair(request_id=str(req.id), helper_id=str(helper.id),
                           seeker_id=str(seeker.id), chat_key="ck").insert()

    await bridge_bot.finish_pair({"vk_user_id": 100, "peer_id": 100}, vk)

    fresh = await TutorPair.get(pair.id)
    assert fresh.status == "closed" and fresh.closed_at is not None
    assert (await HelpRequest.get(req.id)).status == "closed"
    assert any(p["type"] == "bridge.pair_closed" for p in
               (json.loads(x) for x in fake_redis.published))
    # обоим ушла клавиатура оценок со state flow=rate
    for peer in (100, 200):
        st = json.loads(fake_redis.data[f"bridgestate:{peer}"])
        assert st["flow"] == "rate" and st["pair_id"] == str(pair.id)
    assert any("Оцените помощь" in c["message"] for c in _calls_to(vk, 100))
    assert any("Оцените помощь" in c["message"] for c in _calls_to(vk, 200))

    kb = json.loads(_calls_to(vk, 100)[0]["keyboard"])
    payloads = {b["action"]["payload"] for row in kb["buttons"] for b in row}
    for role_vk, score in ((100, 5), (200, 4)):
        vk.calls.clear()
        # жмём кнопку с нужной оценкой
        target = next(p for p in payloads if json.loads(p)["v"] == str(score))
        await bridge_bot.handle_message({"vk_user_id": role_vk, "peer_id": role_vk,
                                         "payload": target, "text": str(score)}, vk)
        assert "bridgestate:%s" % role_vk not in fake_redis.data
    fresh = await TutorPair.get(pair.id)
    assert fresh.helper_score == 5 and fresh.seeker_score == 4


async def test_finish_without_pair(db, fake_redis, vk):
    await _mk_user(100)
    await bridge_bot.finish_pair({"vk_user_id": 100, "peer_id": 100}, vk)
    assert any("Активной пары нет" in c["message"] for c in _calls_to(vk, 100))


async def test_report_flow(db, fake_redis, vk):
    helper = await _mk_user(100, "Помощник")
    seeker = await _mk_user(200, "Заявитель")
    await TutorPair(helper_id=str(helper.id), seeker_id=str(seeker.id), chat_key="ck").insert()

    await bridge_bot.start_report({"vk_user_id": 200, "peer_id": 200}, vk)
    await bridge_bot.handle_message({"vk_user_id": 200, "peer_id": 200,
                                     "text": "предлагал списать"}, vk)
    report = (await Report.find_all().to_list())[0]
    assert report.reporter_id == str(seeker.id)
    assert report.reported_user_id == str(helper.id)
    assert report.reason == "предлагал списать" and report.status == "open"
    assert "bridgestate:200" not in fake_redis.data
    assert any("Жалоба отправлена" in c["message"] for c in _calls_to(vk, 200))


async def test_commands_via_dispatcher(db, fake_redis, vk):
    dp = Dispatcher()
    register(dp)
    await _mk_user(100)
    await dp.dispatch({"text": "стать помощником", "vk_user_id": 100, "peer_id": 100, "vk": vk})
    assert "bridgestate:100" in fake_redis.data
    await dp.dispatch({"text": "отмена", "vk_user_id": 100, "peer_id": 100, "vk": vk})
    assert "bridgestate:100" not in fake_redis.data
    # регэксп «помощник» тоже работает
    await dp.dispatch({"text": "Помощник", "vk_user_id": 100, "peer_id": 100, "vk": vk})
    assert "bridgestate:100" in fake_redis.data


async def test_text_without_pair_or_state_ignored(db, fake_redis, vk):
    await _mk_user(100)
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "просто текст"}, vk)
    assert vk.calls == []


async def test_poll_state_takes_priority(db, fake_redis, vk):
    helper = await _mk_user(100, "П")
    seeker = await _mk_user(200, "З")
    await TutorPair(helper_id=str(helper.id), seeker_id=str(seeker.id), chat_key="ck").insert()
    # юзер посреди опроса — bridge его текст не трогает
    fake_redis.data["pollstate:100"] = json.dumps({"poll_id": "x", "idx": 0})
    await bridge_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "text": "привет"}, vk)
    assert len(await PairMessage.find_all().to_list()) == 0
    assert _calls_to(vk, 200) == []
