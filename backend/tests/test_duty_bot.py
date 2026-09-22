from conftest import ensure_school
import json
from datetime import datetime, timezone

import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

from app.bot import duty_bot
from app.core import redis as core_redis
from app.modules.duty.models import DutyCompletion, DutySchedule, DutyZone, EmbeddedSlot
from app.modules.users.models import School, User

# фиксированный «сейчас»: среда (weekday 3) 2026-09-16, 07:35 локального (UTC+3) = 04:35 UTC
NOW = datetime(2026, 9, 16, 4, 35, tzinfo=timezone.utc)
# 07:57 локального — окно «начало» слота 1 (8:00)
TICK_START = datetime(2026, 9, 16, 4, 57, tzinfo=timezone.utc)
# 10:00 локального — слот 1 давно прошёл, вне обоих окон
TICK_LATE = datetime(2026, 9, 16, 7, 0, tzinfo=timezone.utc)


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def set(self, key, value, nx=True, ex=None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)

    async def delete(self, *keys):
        return 0


class FakeVK:
    def __init__(self):
        self.calls: list[dict] = []

    async def call(self, method, **params):
        self.calls.append({"method": method, **params})


@pytest_asyncio.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(client.get_database("test"),
                      document_models=[School, User, DutyZone, DutySchedule, DutyCompletion])
    yield


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    fr = FakeRedis()
    monkeypatch.setattr(core_redis, "get_redis", lambda: fr)
    monkeypatch.setattr(duty_bot, "_r", lambda: fr)
    return fr


@pytest_asyncio.fixture
async def vk():
    return FakeVK()


async def _mk_student(vk_id: int | None = 100) -> User:
    u = User(school_id=await ensure_school(), login=f"s{vk_id}", password_hash="x", full_name="У",
             role="student", vk_id=vk_id)
    await u.insert()
    return u


async def _mk_schedule(user_id: str, slots: list[tuple[int, int]],
                       zone: str = "Столовая") -> DutySchedule:
    z = DutyZone(school_id=await ensure_school(), name=zone)
    await z.insert()
    return await DutySchedule(school_id=await ensure_school(), teacher_id="t", zone_id=str(z.id),
                              week_pattern=[EmbeddedSlot(weekday=w, slot=s, user_id=user_id)
                                            for w, s in slots]).insert()


async def test_nearest_slot_today_with_button(db, fake_redis, vk):
    u = await _mk_student()
    s = await _mk_schedule(str(u.id), [(3, 1), (4, 1)])
    await duty_bot.handle_duty({"vk_user_id": 100, "peer_id": 100}, vk, now=NOW)
    msg = vk.calls[0]["message"]
    assert "Столовая" in msg and "Среда" in msg and "слот 1" in msg
    assert "keyboard" in vk.calls[0]
    payload = json.loads(vk.calls[0]["keyboard"])["buttons"][0][0]["action"]["payload"]
    assert json.loads(payload) == {"duty": "done", "schedule_id": str(s.id),
                                   "weekday": 3, "slot": 1}


async def test_nearest_slot_tomorrow_no_button(db, fake_redis, vk):
    u = await _mk_student()
    await _mk_schedule(str(u.id), [(4, 1)])
    await duty_bot.handle_duty({"vk_user_id": 100, "peer_id": 100}, vk, now=NOW)
    msg = vk.calls[0]["message"]
    assert "Четверг" in msg
    assert "keyboard" not in vk.calls[0]


async def test_no_duty(db, fake_redis, vk):
    u = await _mk_student()
    await _mk_schedule(str(u.id), [(2, 1)])  # вторник уже прошёл
    await duty_bot.handle_duty({"vk_user_id": 100, "peer_id": 100}, vk, now=NOW)
    assert vk.calls[0]["message"] == duty_bot.NO_DUTY


async def test_done_creates_completion_and_dedups(db, fake_redis, vk):
    u = await _mk_student()
    s = await _mk_schedule(str(u.id), [(3, 1)])
    await duty_bot.handle_duty({"vk_user_id": 100, "peer_id": 100}, vk, now=NOW)
    payload = json.loads(vk.calls[0]["keyboard"])["buttons"][0][0]["action"]["payload"]

    await duty_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "payload": payload}, vk, now=NOW)
    comps = await DutyCompletion.find_all().to_list()
    assert len(comps) == 1
    assert comps[0].weekday == 3 and comps[0].slot == 1
    assert comps[0].date.strftime("%Y-%m-%d") == "2026-09-16"
    assert duty_bot.DONE in vk.calls[1]["message"]

    await duty_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "payload": payload}, vk, now=NOW)
    assert len(await DutyCompletion.find_all().to_list()) == 1
    assert duty_bot.ALREADY_DONE in vk.calls[2]["message"]


async def test_done_ignores_foreign_slot(db, fake_redis, vk):
    await _mk_student()
    other = await _mk_student(vk_id=200)
    s = await _mk_schedule(str(other.id), [(3, 1)])
    payload = json.dumps({"duty": "done", "schedule_id": str(s.id), "weekday": 3, "slot": 1})
    await duty_bot.handle_message({"vk_user_id": 100, "peer_id": 100, "payload": payload}, vk, now=NOW)
    assert vk.calls == []
    assert len(await DutyCompletion.find_all().to_list()) == 0


async def test_tick_soon_window_and_antidup(db, fake_redis, vk):
    u = await _mk_student()
    await _mk_schedule(str(u.id), [(3, 1)])
    await duty_bot.duty_tick(NOW, vk)  # 07:35 — окно 25-35 мин до слота 1
    assert len(vk.calls) == 1
    assert "Через 30 минут" in vk.calls[0]["message"]
    assert any(k.startswith("duty_rem:") for k in fake_redis.data)

    vk.calls.clear()
    await duty_bot.duty_tick(NOW, vk)  # второй вызов — антидубль, тишина
    assert vk.calls == []


async def test_tick_start_window(db, fake_redis, vk):
    u = await _mk_student()
    await _mk_schedule(str(u.id), [(3, 1)])
    await duty_bot.duty_tick(TICK_START, vk)
    assert len(vk.calls) == 1
    assert "Пора на дежурство" in vk.calls[0]["message"]


async def test_tick_outside_window_silent(db, fake_redis, vk):
    u = await _mk_student()
    await _mk_schedule(str(u.id), [(3, 1)])
    await duty_bot.duty_tick(TICK_LATE, vk)
    assert vk.calls == []


async def test_tick_skips_other_weekday_and_userless(db, fake_redis, vk):
    u = await _mk_student()
    no_vk = User(school_id=await ensure_school(), login="s9", password_hash="x", full_name="У", role="student", vk_id=None)
    await no_vk.insert()
    await _mk_schedule(str(u.id), [(4, 1)])      # четверг — не сегодня
    await _mk_schedule(str(no_vk.id), [(3, 1)])  # слот есть, vk не привязан
    await duty_bot.duty_tick(NOW, vk)
    assert vk.calls == []
