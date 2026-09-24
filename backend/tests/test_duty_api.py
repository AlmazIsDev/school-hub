from conftest import ensure_school
import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.users.models import School, SchoolClass, User
from app.modules.pulse.models import Poll, PollAnswer
from app.modules.bridge.models import (Ban, HelpRequest, HelperTopic, PairMessage,
                                       Report, StopWord, TutorPair)
from app.modules.duty.models import DutyCompletion, DutySchedule, DutyZone

ALL_MODELS = [School, User, SchoolClass, Poll, PollAnswer,
              HelperTopic, HelpRequest, TutorPair, PairMessage, Report, Ban, StopWord,
              DutyZone, DutySchedule, DutyCompletion]


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
            "student": await _mk_user("s1", "student"),
            "student2": await _mk_user("s2", "student"),
            "student3": await _mk_user("s3", "student")}


# ---------- zones ----------

async def test_zones_crud_rights(client, tokens):
    # student не может создавать/удалять
    r = await client.post("/api/duty/zones", json={"name": "X"}, headers=_h(tokens["student"]))
    assert r.status_code == 403
    r = await client.post("/api/duty/zones", json={"name": "Спортзал"}, headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    zone_id = r.json()["id"]
    r = await client.delete(f"/api/duty/zones/{zone_id}", headers=_h(tokens["student"]))
    assert r.status_code == 403
    # читать всем
    r = await client.get("/api/duty/zones", headers=_h(tokens["student"]))
    assert r.status_code == 200 and len(r.json()) == 1
    # админ тоже может создать и удалить
    r = await client.post("/api/duty/zones", json={"name": "  "}, headers=_h(tokens["admin"]))
    assert r.status_code == 422
    r = await client.post("/api/duty/zones", json={"name": "Актовый зал"}, headers=_h(tokens["admin"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/duty/zones/{r.json()['id']}", headers=_h(tokens["admin"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/duty/zones/{zone_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/duty/zones/{zone_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 404


# ---------- schedules ----------

async def test_schedule_validation(client, tokens):
    zone_id = (await client.post("/api/duty/zones", json={"name": "Z"}, headers=_h(tokens["teacher"]))).json()["id"]
    teacher_h = _h(tokens["teacher"])
    other = await User.find_one(User.role == "teacher")
    student = await User.find_one(User.role == "student")
    sid = str(student.id)

    # weekday вне 1..7 - проверяется именно валидация диапазона, id валидный
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 8, "slot": 1, "user_id": sid}]})
    assert r.status_code == 422
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 0, "slot": 1, "user_id": sid}]})
    assert r.status_code == 422
    # slot вне 1..8
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 0, "user_id": sid}]})
    assert r.status_code == 422
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 9, "user_id": sid}]})
    assert r.status_code == 422
    # дубликат слота
    slot = {"weekday": 1, "slot": 1, "user_id": sid}
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id, "week_pattern": [slot, dict(slot)]})
    assert r.status_code == 422
    # пустой pattern
    r = await client.post("/api/duty/schedules", headers=teacher_h,
                          json={"zone_id": zone_id, "week_pattern": []})
    assert r.status_code == 422
    # user_id не существует
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 1, "user_id": "0" * 24}]})
    assert r.status_code == 422
    # user_id не ученик
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": zone_id,
        "week_pattern": [{"weekday": 1, "slot": 1, "user_id": str(other.id)}]})
    assert r.status_code == 422
    # зона не найдена
    r = await client.post("/api/duty/schedules", headers=teacher_h, json={
        "zone_id": "0" * 24, "week_pattern": [{"weekday": 1, "slot": 1, "user_id": str(other.id)}]})
    assert r.status_code == 404
    # student не может создавать
    r = await client.post("/api/duty/schedules", headers=_h(tokens["student"]), json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 1, "user_id": str(other.id)}]})
    assert r.status_code == 403


async def test_schedule_read_and_delete(client, tokens):
    students = await User.find(User.role == "student").to_list()
    s1, s2 = str(students[0].id), str(students[1].id)
    zone_id = (await client.post("/api/duty/zones", json={"name": "Z"}, headers=_h(tokens["teacher"]))).json()["id"]
    r = await client.post("/api/duty/schedules", headers=_h(tokens["teacher"]), json={
        "zone_id": zone_id,
        "week_pattern": [{"weekday": 1, "slot": 1, "user_id": s1},
                         {"weekday": 2, "slot": 3, "user_id": s2}]})
    assert r.status_code == 200
    sched_id = r.json()["id"]

    # чтение всем залогиненным, фильтр по user_id
    r = await client.get("/api/duty/schedules", headers=_h(tokens["student"]))
    assert r.status_code == 200 and len(r.json()) == 1 and len(r.json()[0]["week_pattern"]) == 2
    r = await client.get("/api/duty/schedules", params={"user_id": s2}, headers=_h(tokens["student"]))
    assert [s["user_id"] for s in r.json()[0]["week_pattern"]] == [s2]

    # удалить может только владелец-учитель или админ
    r = await client.delete(f"/api/duty/schedules/{sched_id}", headers=_h(tokens["admin"]))
    assert r.status_code == 200
    r = await client.post("/api/duty/schedules", headers=_h(tokens["teacher"]), json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 1, "user_id": s1}]})
    sched_id = r.json()["id"]
    r = await client.delete(f"/api/duty/schedules/{sched_id}", headers=_h(tokens["student"]))
    assert r.status_code == 403
    r = await client.delete(f"/api/duty/schedules/{sched_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/duty/schedules/{sched_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 404

    # зону с живым графиком удалить нельзя
    r = await client.post("/api/duty/schedules", headers=_h(tokens["teacher"]), json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 1, "user_id": s1}]})
    sched_id = r.json()["id"]
    r = await client.delete(f"/api/duty/zones/{zone_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 409
    r = await client.delete(f"/api/duty/schedules/{sched_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 200
    r = await client.delete(f"/api/duty/zones/{zone_id}", headers=_h(tokens["teacher"]))
    assert r.status_code == 200


# ---------- completions ----------

async def test_completions(client, tokens):
    zone_id = (await client.post("/api/duty/zones", json={"name": "Z"}, headers=_h(tokens["teacher"]))).json()["id"]
    students = await User.find(User.role == "student").to_list()
    s1 = str(students[0].id)
    r = await client.post("/api/duty/schedules", headers=_h(tokens["teacher"]), json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 2, "user_id": s1}]})
    sched_id = r.json()["id"]

    # отметка чужого учеником
    r = await client.post("/api/duty/completions", headers=_h(tokens["student2"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "2026-09-14", "user_id": s1})
    assert r.status_code == 403

    # слот не его / нет в графике
    r = await client.post("/api/duty/completions", headers=_h(tokens["student"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 5, "date": "2026-09-14"})
    assert r.status_code == 404

    # своя отметка
    r = await client.post("/api/duty/completions", headers=_h(tokens["student"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "2026-09-14"})
    assert r.status_code == 200

    # дубль
    r = await client.post("/api/duty/completions", headers=_h(tokens["student"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "2026-09-14"})
    assert r.status_code == 409
    # другая дата - не дубль
    r = await client.post("/api/duty/completions", headers=_h(tokens["student"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "2026-09-21"})
    assert r.status_code == 200

    # учитель отмечает за ученика
    r = await client.post("/api/duty/completions", headers=_h(tokens["teacher"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "2026-09-28", "user_id": s1})
    assert r.status_code == 200
    # учитель отмечает за себя - слота нет
    r = await client.post("/api/duty/completions", headers=_h(tokens["teacher"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "2026-09-28"})
    assert r.status_code == 404

    # битая дата
    r = await client.post("/api/duty/completions", headers=_h(tokens["student"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2, "date": "14.09.2026"})
    assert r.status_code == 422

    # статистика: ученик видит только себя
    r = await client.get("/api/duty/completions", headers=_h(tokens["student"]))
    assert r.status_code == 200 and len(r.json()) == 3
    other_student = str(students[1].id)
    r = await client.get("/api/duty/completions", params={"user_id": other_student}, headers=_h(tokens["student"]))
    assert r.status_code == 403
    # учитель - любых, с фильтром по датам
    r = await client.get("/api/duty/completions", params={"user_id": s1, "from": "2026-09-20", "to": "2026-09-25"},
                         headers=_h(tokens["teacher"]))
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]["date"][:10] == "2026-09-21"


async def test_duty_stats(client, tokens):
    from datetime import datetime, timedelta, timezone
    zone_id = (await client.post("/api/duty/zones", json={"name": "Z2"}, headers=_h(tokens["teacher"]))).json()["id"]
    s1 = str((await User.find_one(User.role == "student")).id)
    r = await client.post("/api/duty/schedules", headers=_h(tokens["teacher"]), json={
        "zone_id": zone_id, "week_pattern": [{"weekday": 1, "slot": 2, "user_id": s1}]})
    sched_id = r.json()["id"]

    # график действует две недели
    sched = await DutySchedule.get(sched_id)
    today = datetime.now(timezone.utc).date()
    sched.created_at = datetime.now(timezone.utc) - timedelta(days=14)
    await sched.save()

    # отметка за понедельник текущей недели
    monday = today - timedelta(days=today.weekday())
    r = await client.post("/api/duty/completions", headers=_h(tokens["student"]), json={
        "schedule_id": sched_id, "weekday": 1, "slot": 2,
        "date": monday.isoformat()})
    assert r.status_code == 200

    r = await client.get("/api/duty/stats", headers=_h(tokens["student"]))
    assert r.status_code == 200
    # прошедшие понедельники с момента создания графика: отмеченный - done, остальные - missed; сегодняшний день не считаем
    mondays = []
    d = today - timedelta(days=14)
    while d <= today:
        if d.weekday() == 0 and d != today:
            mondays.append(d)
        d += timedelta(days=1)
    assert r.json() == {"done": 1, "missed": len(mondays) - 1}
