import json
import logging
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from ...core import redis as core_redis
from ...core.security import get_current_user, require_role
from ..users import service as users_service
from . import schemas
from .models import EmbeddedQuestion, Poll

log = logging.getLogger("pulse")
router = APIRouter(prefix="/api/pulse", tags=["pulse"])


def poll_out(p: Poll) -> dict:
    return {"id": str(p.id), "title": p.title, "topic": p.topic, "status": p.status,
            "class_id": p.class_id, "questions": [q.model_dump() for q in p.questions],
            "created_at": p.created_at, "closed_at": p.closed_at}


async def get_poll(poll_id: str) -> Poll:
    try:
        poll = await Poll.get(ObjectId(poll_id))
    except Exception:
        poll = None
    if not poll:
        raise HTTPException(404, "Опрос не найден")
    return poll


def _can_manage(poll: Poll, user: dict) -> bool:
    return user["role"] == "admin" or poll.teacher_id == user["id"]


@router.post("/polls")
async def create_poll(body: schemas.PollCreateIn, user: dict = Depends(require_role("teacher", "admin"))):
    for q in body.questions:
        if q.type not in ("scale1_5", "free_text"):
            raise HTTPException(422, "Тип вопроса не в списке")
    poll = Poll(teacher_id=user["id"], class_id=body.class_id, title=body.title,
                topic=body.topic,
                questions=[EmbeddedQuestion(text=q.text, type=q.type) for q in body.questions])
    await poll.insert()
    return {"id": str(poll.id)}


@router.post("/polls/{poll_id}/publish")
async def publish_poll(poll_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    poll = await get_poll(poll_id)
    if not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    if poll.status != "draft":
        raise HTTPException(409, "Опрос уже опубликован")
    poll.status = "active"
    await poll.save()
    return poll_out(poll)


@router.post("/polls/{poll_id}/close")
async def close_poll(poll_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    poll = await get_poll(poll_id)
    if not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    if poll.status != "active":
        raise HTTPException(409, "Опрос не активен")
    poll.status, poll.closed_at = "closed", datetime.now(timezone.utc)
    await poll.save()
    try:
        await core_redis.get_redis().publish(
            "events", json.dumps({"type": "poll.closed", "poll_id": str(poll.id)}))
    except Exception as e:
        # close не должен падать из-за недоступного redis — подписчик потеряет событие, но статус уже сохранён
        log.warning("poll.closed не опубликован: %s", e)
    return poll_out(poll)


@router.get("/polls")
async def list_polls(user: dict = Depends(get_current_user)):
    if user["role"] in ("teacher", "admin"):
        rows = await Poll.find(Poll.teacher_id == user["id"]).to_list()
    else:
        u = await users_service.by_id(user["id"])
        if not u or not u.class_id:
            return []
        rows = await Poll.find(Poll.class_id == u.class_id, Poll.status == "active").to_list()
    return [poll_out(p) for p in rows]


@router.get("/polls/{poll_id}")
async def get_poll_view(poll_id: str, user: dict = Depends(get_current_user)):
    poll = await get_poll(poll_id)
    if user["role"] == "student":
        u = await users_service.by_id(user["id"])
        if poll.status != "active" or not u or poll.class_id != u.class_id:
            raise HTTPException(403, "Опрос недоступен")
    elif not _can_manage(poll, user):
        raise HTTPException(403, "Не ваш опрос")
    return poll_out(poll)
