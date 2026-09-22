import csv
import io
import logging
from collections import Counter
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ...core import events
from ...core.security import get_current_user, require_role
from ..users import service as users_service
from ...modules.users.models import SchoolClass
from . import schemas
from .models import EmbeddedQuestion, Poll, PollAnswer

log = logging.getLogger("pulse")
router = APIRouter(prefix="/api/pulse", tags=["pulse"])


def poll_out(p: Poll) -> dict:
    return {"id": str(p.id), "title": p.title, "topic": p.topic, "status": p.status,
            "class_id": p.class_id, "questions": [q.model_dump() for q in p.questions],
            "created_at": p.created_at, "closed_at": p.closed_at}


async def get_poll(poll_id: str, user: dict) -> Poll:
    try:
        poll = await Poll.get(ObjectId(poll_id))
    except (InvalidId, TypeError):
        poll = None
    if not poll or poll.school_id != user.get("school_id"):
        raise HTTPException(404, "Опрос не найден")
    return poll
    try:
        poll = await Poll.get(ObjectId(poll_id))
    except (InvalidId, TypeError):
        poll = None
    if not poll or poll.school_id != school_id:
        raise HTTPException(404, "Опрос не найден")
    return poll


def _can_manage(poll: Poll, user: dict) -> bool:
    return user["role"] == "admin" or poll.teacher_id == user["id"]


@router.post("/polls")
async def create_poll(body: schemas.PollCreateIn, user: dict = Depends(require_role("teacher", "admin"))):
    try:
        school_class = await SchoolClass.get(ObjectId(body.class_id))
    except (InvalidId, TypeError):
        school_class = None
    if not school_class or school_class.school_id != user.get("school_id"):
        raise HTTPException(404, "Класс не найден")
    poll = Poll(school_id=user["school_id"], teacher_id=user["id"], class_id=body.class_id,
                title=body.title, topic=body.topic,
                questions=[EmbeddedQuestion(text=q.text, type=q.type) for q in body.questions])
    await poll.insert()
    return {"id": str(poll.id)}


@router.post("/polls/{poll_id}/publish")
async def publish_poll(poll_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    poll = await get_poll(poll_id, user)
    if not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    if poll.status == "closed":
        raise HTTPException(409, "Опрос закрыт")
    if poll.status != "draft":
        raise HTTPException(409, "Опрос уже опубликован")
    poll.status = "active"
    await poll.save()
    await events.publish("poll.published", poll_id=str(poll.id))
    return poll_out(poll)


@router.post("/polls/{poll_id}/close")
async def close_poll(poll_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    poll = await get_poll(poll_id, user)
    if not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    if poll.status != "active":
        raise HTTPException(409, "Опрос не активен")
    poll.status, poll.closed_at = "closed", datetime.now(timezone.utc)
    await poll.save()
    await events.publish("poll.closed", poll_id=str(poll.id))
    return poll_out(poll)


@router.get("/polls")
async def list_polls(user: dict = Depends(get_current_user)):
    if user["role"] == "admin":
        rows = await Poll.find(Poll.school_id == user["school_id"]).to_list()
    elif user["role"] == "teacher":
        rows = await Poll.find(Poll.teacher_id == user["id"]).to_list()
    else:
        u = await users_service.by_id(user["id"])
        if not u or not u.class_id:
            return []
        rows = await Poll.find(Poll.class_id == u.class_id, Poll.status == "active").to_list()
    return [poll_out(p) for p in rows]


@router.get("/polls/{poll_id}")
async def get_poll_view(poll_id: str, user: dict = Depends(get_current_user)):
    poll = await get_poll(poll_id, user)
    if user["role"] == "student":
        u = await users_service.by_id(user["id"])
        if poll.status != "active" or not u or poll.class_id != u.class_id:
            raise HTTPException(403, "Опрос недоступен")
    elif not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    return poll_out(poll)


@router.get("/polls/{poll_id}/results")
async def poll_results(poll_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    poll = await get_poll(poll_id, user)
    if not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    answers = await PollAnswer.find(PollAnswer.poll_id == poll_id,
                                    PollAnswer.school_id == user["school_id"]).to_list()

    # Анонимные ответы — связать их между собой нельзя, поэтому completed/started
    # считаем как число ответов на последний / первый вопрос соответственно
    # (нижняя граница: ученик, дошедший до последнего вопроса, мог пропустить первый).
    last_idx = len(poll.questions) - 1
    started = sum(1 for a in answers if a.question_idx == 0)
    completed = sum(1 for a in answers if a.question_idx == last_idx)

    questions = []
    for idx, q in enumerate(poll.questions):
        values = [a.value for a in answers if a.question_idx == idx]
        if q.type == "scale1_5":
            # считаем все значения шкалы, включая нули
            counts = {str(v): 0 for v in range(1, 6)}
            for v in values:
                if v in counts:
                    counts[v] += 1
            questions.append({"text": q.text, "type": q.type, "answers": counts})
        else:
            questions.append({"text": q.text, "type": q.type, "answers": values})
    return {
        "poll": {"title": poll.title, "topic": poll.topic, "status": poll.status},
        "completed": completed,
        "started": started,
        "questions": questions,
    }


@router.get("/polls/{poll_id}/results.csv")
async def poll_results_csv(poll_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    """CSV для Excel: ; и BOM, ответы анонимны — агрегаты по вопросам."""
    poll = await get_poll(poll_id, user)
    if not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    answers = await PollAnswer.find(PollAnswer.poll_id == poll_id,
                                    PollAnswer.school_id == user["school_id"]).to_list()

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["Опрос", poll.title, "Тема", poll.topic, "Статус", poll.status])
    w.writerow([])
    w.writerow(["Вопрос", "Тип", "Ответ", "Количество"])
    for idx, q in enumerate(poll.questions):
        values = [a.value for a in answers if a.question_idx == idx]
        if q.type == "scale1_5":
            counts = Counter(v for v in values if v in {"1", "2", "3", "4", "5"})
            for v in "12345":
                w.writerow([q.text, q.type, v, counts.get(v, 0)])
        else:
            for v in values:
                w.writerow([q.text, q.type, v, 1])
    # utf-8-sig, чтобы Excel открывал кириллицу без настроек
    return Response(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="poll-{poll_id}.csv"'})


@router.get("/topics")
async def weak_topics(threshold: float = 3.5, user: dict = Depends(require_role("teacher", "admin"))):
    if not (0 < threshold <= 5):
        raise HTTPException(422, "threshold должен быть в (0, 5]")
    # Только closed: средняя по активному опросу вводит в заблуждение —
    # ответили ещё не все, да и учитель не «отработал» результат.
    query = {"status": "closed", "school_id": user.get("school_id")}
    if user["role"] != "admin":
        query["teacher_id"] = user["id"]
    polls = await Poll.find(query).to_list()

    out = []
    for p in polls:
        answers = await PollAnswer.find(PollAnswer.poll_id == str(p.id),
                                        PollAnswer.school_id == user["school_id"]).to_list()
        scale_idx = {i for i, q in enumerate(p.questions) if q.type == "scale1_5"}
        vals = [int(a.value) for a in answers
                if a.question_idx in scale_idx and a.value.isdigit() and 1 <= int(a.value) <= 5]
        if not vals:
            continue  # без данных средняя бессмысленна
        avg = sum(vals) / len(vals)
        if avg < threshold:
            out.append({"poll_id": str(p.id), "title": p.title, "topic": p.topic,
                        "avg": round(avg, 2), "n_answers": len(vals)})
    out.sort(key=lambda x: x["avg"])
    return out


@router.get("/compare")
async def compare_polls(a: str, b: str, user: dict = Depends(require_role("teacher", "admin"))):
    if a == b:
        raise HTTPException(400, "Нужны два разных опроса")
    poll_a, poll_b = await get_poll(a, user), await get_poll(b, user)
    for p in (poll_a, poll_b):
        if user["role"] != "admin" and p.teacher_id != user["id"]:
            raise HTTPException(403, "Не ваш опрос")
        if p.status != "closed":
            raise HTTPException(409, f"Опрос «{p.title}» не закрыт")
    if poll_a.topic != poll_b.topic:
        raise HTTPException(400, "Темы опросов не совпадают")

    async def scale_avgs(p: Poll) -> list[float | None]:
        answers = await PollAnswer.find(PollAnswer.poll_id == str(p.id),
                                        PollAnswer.school_id == user["school_id"]).to_list()
        by_q: dict[int, list[int]] = {}
        for ans in answers:
            if 0 <= ans.question_idx < len(p.questions) and p.questions[ans.question_idx].type == "scale1_5" \
                    and ans.value.isdigit() and 1 <= int(ans.value) <= 5:
                by_q.setdefault(ans.question_idx, []).append(int(ans.value))
        n = max((i for i, q in enumerate(p.questions) if q.type == "scale1_5"), default=-1) + 1
        return [round(sum(v) / len(v), 2) if (v := by_q.get(i)) else None for i in range(n)]

    return {"a": {"title": poll_a.title, "avgs": await scale_avgs(poll_a)},
            "b": {"title": poll_b.title, "avgs": await scale_avgs(poll_b)}}
