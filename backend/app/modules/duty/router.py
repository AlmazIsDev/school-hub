from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from ...core.security import get_current_user, require_role
from ..users.models import User
from . import schemas
from .models import DutyCompletion, DutySchedule, DutyZone, EmbeddedSlot

router = APIRouter(prefix="/api/duty", tags=["duty"])


def _get(doc_id: str):
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Не найдено")


def _school(user: dict) -> str:
    sid = user.get("school_id")
    if not sid:
        raise HTTPException(403, "Только для сотрудников школы")
    return sid


def _slot_out(s) -> dict:
    return {"weekday": s.weekday, "slot": s.slot, "user_id": s.user_id}


def _parse_date(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")


@router.post("/zones")
async def create_zone(body: schemas.ZoneIn, user: dict = Depends(require_role("teacher", "admin"))):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Пустое название зоны")
    zone = DutyZone(school_id=_school(user), name=name)
    await zone.insert()
    return {"id": str(zone.id), "name": zone.name}


@router.get("/zones")
async def list_zones(user: dict = Depends(get_current_user)):
    return [{"id": str(z.id), "name": z.name, "created_at": z.created_at}
            for z in await DutyZone.find(DutyZone.school_id == _school(user)).to_list()]


@router.delete("/zones/{zone_id}")
async def delete_zone(zone_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    zone = await DutyZone.get(_get(zone_id))
    if not zone or zone.school_id != _school(user):
        raise HTTPException(404, "Зона не найдена")
    if await DutySchedule.find_one(DutySchedule.zone_id == zone_id):
        raise HTTPException(409, "Сначала удали графики")
    await zone.delete()
    return {"ok": True}


@router.post("/schedules")
async def create_schedule(body: schemas.ScheduleIn, user: dict = Depends(require_role("teacher", "admin"))):
    zone = await DutyZone.get(_get(body.zone_id))
    if not zone or zone.school_id != _school(user):
        raise HTTPException(404, "Зона не найдена")

    # валидация учеников: каждый user_id — существующий User с role=student
    ids = {s.user_id for s in body.week_pattern}
    try:
        oids = [ObjectId(i) for i in ids]
    except (InvalidId, TypeError):
        raise HTTPException(422, "user_id должен быть ObjectId")
    found = await User.find({"_id": {"$in": oids}, "school_id": _school(user)}).to_list()
    by_id = {str(u.id): u for u in found}
    for uid in ids:
        u = by_id.get(uid)
        if not u or u.role != "student":
            raise HTTPException(422, f"user_id {uid} не является учеником")

    # дубликат слота (weekday, slot, user_id) в одном графике — ошибка
    seen = {(s.weekday, s.slot, s.user_id) for s in body.week_pattern}
    if len(seen) != len(body.week_pattern):
        raise HTTPException(422, "Дубликат слота в week_pattern")

    # изменения графика = delete + create, PUT для schedules сознательно не делаем (YAGNI)
    schedule = DutySchedule(school_id=_school(user), teacher_id=user["id"], zone_id=body.zone_id,
                            week_pattern=[EmbeddedSlot(**s.model_dump()) for s in body.week_pattern])
    await schedule.insert()
    return {"id": str(schedule.id), "teacher_id": schedule.teacher_id,
            "zone_id": schedule.zone_id,
            "week_pattern": [_slot_out(s) for s in schedule.week_pattern]}


@router.get("/schedules")
async def list_schedules(user_id: str | None = None, user: dict = Depends(get_current_user)):
    query = DutySchedule.find(DutySchedule.school_id == _school(user))
    if user_id:
        query = DutySchedule.find(DutySchedule.school_id == _school(user),
                                  DutySchedule.week_pattern.user_id == user_id)
    out = []
    for s in await query.to_list():
        slots = [_slot_out(x) for x in s.week_pattern if not user_id or x.user_id == user_id]
        if slots:
            out.append({"id": str(s.id), "teacher_id": s.teacher_id, "zone_id": s.zone_id,
                        "week_pattern": slots, "created_at": s.created_at})
    return out


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str, user: dict = Depends(get_current_user)):
    schedule = await DutySchedule.get(_get(schedule_id))
    if not schedule or schedule.school_id != _school(user):
        raise HTTPException(404, "График не найден")
    if user["role"] != "admin" and schedule.teacher_id != user["id"]:
        raise HTTPException(403, "Недостаточно прав")
    # отметки (completions) при удалении графика не трогаем — история дежурств остаётся
    await schedule.delete()
    return {"ok": True}


@router.post("/completions")
async def create_completion(body: schemas.CompletionIn, user: dict = Depends(get_current_user)):
    schedule = await DutySchedule.get(_get(body.schedule_id))
    if not schedule or schedule.school_id != _school(user):
        raise HTTPException(404, "График не найден")

    if user["role"] in ("teacher", "admin"):
        target_id = body.user_id or user["id"]
    else:
        if body.user_id and body.user_id != user["id"]:
            raise HTTPException(403, "Нельзя отмечать другого ученика")
        target_id = user["id"]

    slot = next((s for s in schedule.week_pattern
                 if s.weekday == body.weekday and s.slot == body.slot and s.user_id == target_id), None)
    if not slot:
        raise HTTPException(404, "Такого слота нет в графике")

    date = _parse_date(body.date)
    if await DutyCompletion.find_one(DutyCompletion.schedule_id == body.schedule_id,
                                     DutyCompletion.weekday == body.weekday,
                                     DutyCompletion.slot == body.slot,
                                     DutyCompletion.user_id == target_id,
                                     DutyCompletion.date == date):
        raise HTTPException(409, "Отметка за эту дату уже есть")
    completion = DutyCompletion(school_id=_school(user), schedule_id=body.schedule_id,
                                weekday=body.weekday,
                                slot=body.slot, user_id=target_id, date=date)
    try:
        await completion.insert()
    except DuplicateKeyError:
        # двойной клик / параллельные POST — compound unique index ловит то,
        # что find_one выше не успел
        raise HTTPException(409, "Отметка за эту дату уже есть")
    return {"id": str(completion.id), "schedule_id": completion.schedule_id,
            "weekday": completion.weekday, "slot": completion.slot,
            "user_id": completion.user_id, "date": body.date,
            "marked_at": completion.marked_at}


@router.get("/completions")
async def list_completions(user_id: str | None = None,
                           from_: str | None = Query(None, alias="from"),
                           to: str | None = None, user: dict = Depends(get_current_user)):
    target_id = user_id or user["id"]
    if user["role"] not in ("teacher", "admin") and target_id != user["id"]:
        raise HTTPException(403, "Нельзя смотреть чужие отметки")

    query: dict = {"school_id": _school(user), "user_id": target_id}
    if from_ or to:
        query["date"] = {}
        if from_:
            query["date"]["$gte"] = _parse_date(from_)
        if to:
            query["date"]["$lte"] = _parse_date(to)
    return [{"id": str(c.id), "schedule_id": c.schedule_id, "weekday": c.weekday,
             "slot": c.slot, "user_id": c.user_id, "date": c.date, "marked_at": c.marked_at}
            for c in await DutyCompletion.find(query).to_list()]


@router.get("/stats")
async def duty_stats(user_id: str | None = None, user: dict = Depends(get_current_user)):
    """Сколько дежурил / сколько пропустил: прошедшие слоты графика
    с момента его создания без отметки считаем пропущенными."""
    target_id = user_id or user["id"]
    if user["role"] not in ("teacher", "admin") and target_id != user["id"]:
        raise HTTPException(403, "Нельзя смотреть чужую статистику")

    today = datetime.now(timezone.utc).date()
    done = missed = 0
    for s in await DutySchedule.find(DutySchedule.school_id == _school(user),
                                     DutySchedule.week_pattern.user_id == target_id).to_list():
        slots = [x for x in s.week_pattern if x.user_id == target_id]
        completions = await DutyCompletion.find(
            DutyCompletion.schedule_id == str(s.id),
            DutyCompletion.user_id == target_id).to_list()
        marked = {(c.weekday, c.slot, c.date.date()) for c in completions}
        # слот начинает действовать с даты создания графика
        start = s.created_at.date() if s.created_at else today
        d = start
        while d <= today:
            if (d.weekday() + 1) in {x.weekday for x in slots}:
                for x in slots:
                    if x.weekday != d.weekday() + 1:
                        continue
                    if d == today:  # сегодня ещё можно отметить
                        continue
                    if (x.weekday, x.slot, d) in marked:
                        done += 1
                    else:
                        missed += 1
            d += timedelta(days=1)
    return {"done": done, "missed": missed}
