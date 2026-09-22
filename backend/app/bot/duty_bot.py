import json
import logging
from datetime import datetime, timedelta, timezone

from ..core import redis as core_redis
from pymongo.errors import DuplicateKeyError

from ..modules.duty.models import DutyCompletion, DutySchedule, DutyZone
from ..modules.users.models import User
from .pulse_bot import _send

log = logging.getLogger("bot")

# школа в РФ: все «сегодня/сейчас» считаем в UTC+3, без зоны в настройках
TZ_OFFSET = 3
REM_TTL = 43200  # 12h — антидубль напоминаний

# ponytail: расписание звонков упрощённое (слот N начинается в 8:00 + (N-1)*60 мин),
# поправить на реальное расписание школы, когда узнаем
SLOT_START_MIN = 8 * 60  # 8:00
SLOT_LEN_MIN = 60

WD = ["", "Понедельник", "Вторник", "Среда", "Четверг",
      "Пятница", "Суббота", "Воскресенье"]
NO_DUTY = "На этой неделе дежурств нет."
ALREADY_DONE = "Уже отметили, спасибо!"
DONE = "Отметил, что ты выполнил дежурство. Молодец!"


def _r():
    return core_redis.get_redis()


def _local(now: datetime) -> datetime:
    return now + timedelta(hours=TZ_OFFSET)


def slot_start_hhmm(slot: int) -> str:
    m = SLOT_START_MIN + (slot - 1) * SLOT_LEN_MIN
    return f"{m // 60:02d}:{m % 60:02d}"


def _now_slot_rank(local: datetime) -> int:
    """Индекс текущего слота: 0 = ещё до первого, N = слот N идёт/начался.
    ponytail: слот считается «прошедшим» с момента начала — длительность
    слота вне рабочего дня (16:00+) не отслеживаем, ранг просто растёт."""
    minutes = local.hour * 60 + local.minute
    return (minutes - SLOT_START_MIN) // SLOT_LEN_MIN + 1


def _kb_done(schedule_id: str, weekday: int, slot: int) -> str:
    return json.dumps({"one_time": True, "buttons": [[
        {"action": {"type": "text", "label": "Выполнил",
                    "payload": json.dumps({"duty": "done", "schedule_id": schedule_id,
                                           "weekday": weekday, "slot": slot})},
         "color": "positive"}]]}, ensure_ascii=False)


async def nearest_slot(user_id: str, now: datetime):
    """Ближайший слот ученика: (schedule, slot) с (weekday, slot) >= сейчас,
    или None. Перенос на следующую неделю не ищем — «на этой неделе нет»."""
    loc = _local(now)
    cur = (loc.isoweekday(), max(1, _now_slot_rank(loc)))
    best = None
    async for s in DutySchedule.find_all():
        for sl in s.week_pattern:
            if sl.user_id != user_id:
                continue
            key = (sl.weekday, sl.slot)
            if key >= cur and (best is None or key < best[1]):
                best = (s, key)
    if not best:
        return None
    zone = await DutyZone.get(best[0].zone_id)
    return best[0], best[1], zone.name if zone else "зона"


async def handle_duty(event, vk, now: datetime | None = None):
    u = await User.find_one(User.vk_id == event["vk_user_id"])
    if not u:
        return
    found = await nearest_slot(str(u.id), now or datetime.now(timezone.utc))
    if not found:
        await _send(vk, event["peer_id"], NO_DUTY)
        return
    schedule, (weekday, slot), zone = found
    msg = (f"Твоё дежурство: {zone}, {WD[weekday]}, "
           f"слот {slot} (начало в {slot_start_hhmm(slot)}).")
    kb = _kb_done(str(schedule.id), weekday, slot) if weekday == _local(now or datetime.now(timezone.utc)).isoweekday() else None
    await _send(vk, event["peer_id"], msg, kb)


async def _on_done(payload: dict, event, vk, now: datetime | None = None):
    vk_id, peer = event["vk_user_id"], event["peer_id"]
    u = await User.find_one(User.vk_id == vk_id)
    if not u:
        return
    weekday, slot = payload.get("weekday"), payload.get("slot")
    try:
        schedule = await DutySchedule.get(payload.get("schedule_id", ""))
    except Exception:
        return
    if not schedule:
        return
    loc = _local(now or datetime.now(timezone.utc))
    # отметка только в день дежурства — старые клавиатуры VK сохраняются в переписке
    if weekday != loc.isoweekday():
        return
    if not any(s.user_id == str(u.id) and s.weekday == weekday and s.slot == slot
               for s in schedule.week_pattern):
        return
    date = datetime(loc.year, loc.month, loc.day, tzinfo=timezone.utc)
    if await DutyCompletion.find_one(DutyCompletion.schedule_id == str(schedule.id),
                                     DutyCompletion.weekday == weekday,
                                     DutyCompletion.slot == slot,
                                     DutyCompletion.user_id == str(u.id),
                                     DutyCompletion.date == date):
        await _send(vk, peer, ALREADY_DONE)
        return
    try:
        await DutyCompletion(school_id=schedule.school_id, schedule_id=str(schedule.id),
                             weekday=weekday,
                             slot=slot, user_id=str(u.id), date=date).insert()
    except DuplicateKeyError:
        # compound unique index ловит гонку двойного клика
        await _send(vk, peer, ALREADY_DONE)
        return
    await _send(vk, peer, DONE)


async def handle_message(event, vk, now: datetime | None = None):
    """Только payload-кнопки duty; текстовые сценарии у нас отсутствуют."""
    raw = event.get("payload")
    if not raw:
        return
    try:
        p = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return
    if isinstance(p, dict) and p.get("duty") == "done":
        await _on_done(p, event, vk, now)


async def duty_tick(now: datetime, vk):
    """Напоминания о слотах сегодня: за 30 мин (окно 25–35) и в начале
    (окно 0–5). Антидубль — Redis-ключ на 12h (get → отправка → set)."""
    loc = _local(now)
    today_wd = loc.isoweekday()
    date = loc.date().isoformat()
    minutes = loc.hour * 60 + loc.minute
    for schedule in await DutySchedule.find_all().to_list():
        zone = None
        users = {}
        for sl in schedule.week_pattern:
            if sl.weekday != today_wd:
                continue
            delta = SLOT_START_MIN + (sl.slot - 1) * SLOT_LEN_MIN - minutes
            if 25 <= delta <= 35:
                kind = "soon"
            elif 0 <= delta <= 5:
                kind = "start"
            else:
                continue
            key = f"duty_rem:{schedule.id}:{sl.weekday}:{sl.slot}:{date}:{kind}"
            if await _r().get(key):
                continue
            if zone is None:
                z = await DutyZone.get(schedule.zone_id)
                zone = z.name if z else "зона"
            if sl.user_id not in users:
                u = await User.get(sl.user_id)
                if u and u.vk_id:
                    users[sl.user_id] = u.vk_id
            if sl.user_id not in users:
                continue
            text = (f"Через 30 минут твоё дежурство: {zone}, слот {sl.slot} "
                    f"(начало в {slot_start_hhmm(sl.slot)})." if kind == "soon" else
                    f"Пора на дежурство: {zone}, слот {sl.slot}.")
            try:
                await _send(vk, users[sl.user_id], text)
            except Exception:
                log.exception("напоминание duty не дошло vk=%s", users[sl.user_id])
                continue
            # ключ только после успешной отправки — при сбое VK напоминание повторится
            await _r().set(key, "1", ex=REM_TTL)
