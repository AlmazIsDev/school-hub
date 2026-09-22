from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import events
from ...core.security import get_current_user, require_role
from ...modules.users.models import SchoolClass, User
from . import schemas, service
from .models import Quest, QuestRun

router = APIRouter(prefix="/api/builder", tags=["builder"])


def _oid(doc_id: str):
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Квест не найден")


async def _get_quest(quest_id: str) -> Quest:
    q = await Quest.get(_oid(quest_id))
    if not q:
        raise HTTPException(404, "Квест не найден")
    return q


def _ensure_can_manage(q: Quest, user: dict) -> None:
    if user["role"] != "admin" and q.teacher_id != user["id"]:
        raise HTTPException(403, "Не твой квест")


@router.post("/quests")
async def create_quest(body: schemas.QuestIn, user: dict = Depends(require_role("teacher", "admin"))):
    if not await SchoolClass.get(_oid(body.class_id)):
        raise HTTPException(404, "Класс не найден")
    q = Quest(teacher_id=user["id"], class_id=body.class_id,
              title=body.title, structure=body.structure.model_dump(by_alias=True))
    await q.insert()
    return schemas.quest_out(q)


@router.get("/quests")
async def list_quests(user: dict = Depends(require_role("teacher", "admin"))):
    flt = {} if user["role"] == "admin" else {"teacher_id": user["id"]}
    return [schemas.quest_out(q) for q in await Quest.find(flt).to_list()]


@router.get("/quests/published")
async def list_published(user: dict = Depends(get_current_user)):
    """Список доступных квестов: ученику — его класс, редакции — все published."""
    flt: dict = {"status": "published"}
    if user["role"] == "student":
        me = await User.get(ObjectId(user["id"]))
        if not me or not me.class_id:
            return []
        flt["class_id"] = me.class_id
    return [{"id": str(q.id), "title": q.title} for q in await Quest.find(flt).to_list()]


@router.get("/quests/{quest_id}")
async def get_quest(quest_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    q = await _get_quest(quest_id)
    _ensure_can_manage(q, user)
    return schemas.quest_out(q)


@router.put("/quests/{quest_id}")
async def update_quest(quest_id: str, body: schemas.QuestIn,
                       user: dict = Depends(require_role("teacher", "admin"))):
    q = await _get_quest(quest_id)
    _ensure_can_manage(q, user)
    if q.status != "draft":
        raise HTTPException(409, "Редактировать можно только draft")
    if not await SchoolClass.get(_oid(body.class_id)):
        raise HTTPException(404, "Класс не найден")
    q.title = body.title
    q.class_id = body.class_id
    q.structure = body.structure.model_dump(by_alias=True)
    await q.save()
    return schemas.quest_out(q)


@router.post("/quests/{quest_id}/publish")
async def publish_quest(quest_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    q = await _get_quest(quest_id)
    _ensure_can_manage(q, user)
    if q.status != "draft":
        raise HTTPException(409, "Опубликовать можно только draft")
    q.status = "published"
    await q.save()
    return {"id": str(q.id), "status": q.status}


@router.post("/quests/{quest_id}/close")
async def close_quest(quest_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    q = await _get_quest(quest_id)
    _ensure_can_manage(q, user)
    if q.status != "published":
        raise HTTPException(409, "Закрыть можно только published")
    q.status = "closed"
    await q.save()
    return {"id": str(q.id), "status": q.status}


@router.get("/quests/{quest_id}/play")
async def play_quest(quest_id: str, user: dict = Depends(get_current_user)):
    q = await _get_quest(quest_id)
    if q.status != "published":
        raise HTTPException(409, "Квест не опубликован")
    # teacher/admin могут смотреть published чужих квестов — превью без класса
    await service.check_class_access(q, user)
    return {"id": str(q.id), "title": q.title, "blocks": service.sanitized_blocks(q)}


class PlayAnswerIn(BaseModel):
    run_id: str
    block_id: str
    value: str | None = None


@router.post("/quests/{quest_id}/play/start")
async def play_start(quest_id: str, user: dict = Depends(get_current_user)):
    q = await _get_quest(quest_id)
    if q.status != "published":
        raise HTTPException(409, "Квест не опубликован")
    await service.check_class_access(q, user)
    run = await QuestRun(quest_id=quest_id, user_id=user["id"], trace=[]).insert()
    blocks = service.blocks_map(q)
    target = service.resolve_next(blocks, q.structure["blocks"][0]["id"], None)
    return _play_state(q, run, blocks, target)


@router.post("/quests/{quest_id}/play/answer")
async def play_answer(quest_id: str, body: PlayAnswerIn,
                      user: dict = Depends(get_current_user)):
    q = await _get_quest(quest_id)
    if q.status != "published":
        raise HTTPException(409, "Квест закрыт.")
    try:
        run = await QuestRun.get(ObjectId(body.run_id))
    except (InvalidId, TypeError):
        raise HTTPException(404, "Прохождение не найдено")
    if not run or run.quest_id != quest_id or run.user_id != user["id"]:
        raise HTTPException(404, "Прохождение не найдено")
    if run.finished:
        raise HTTPException(409, "Квест уже завершён")

    blocks = service.blocks_map(q)
    bid = service.expected_block_id(q, run.trace)
    if bid is None or bid != body.block_id or blocks[bid]["type"] == "end":
        raise HTTPException(409, "Блок не соответствует ходу прохождения")
    b = blocks[bid]
    value = body.value
    if b["type"] == "question":
        if not value or value not in b["options"]:
            raise HTTPException(422, "Ответ должен быть одним из вариантов")
    else:  # hint
        value = None

    run.trace.append({"block_id": bid, "value": value})
    target = service.resolve_next(blocks, b["next"], value)
    return await _advance(q, run, blocks, target)


def _play_state(q: Quest, run: QuestRun, blocks: dict, target: str) -> dict:
    if blocks[target]["type"] == "end":
        return {
            "run_id": str(run.id), "finished": True,
            "score": blocks[target]["score"], "block": None,
        }
    b = blocks[target]
    return {"run_id": str(run.id), "finished": False, "score": None,
            "block": {k: v for k, v in b.items() if k not in ("score", "condition")}}


async def _advance(q: Quest, run: QuestRun, blocks: dict, target: str) -> dict:
    """Сохраняет trace (уже с ответом), при финале закрывает run."""
    if blocks[target]["type"] == "end":
        run.trace.append({"block_id": target, "value": None})
        run.finished = True
        run.score = blocks[target]["score"]
        run.finished_at = datetime.now(timezone.utc)
        await run.save()
        await events.publish("quest.finished", quest_id=str(q.id),
                             run_id=str(run.id), score=run.score)
        return {"run_id": str(run.id), "finished": True,
                "score": run.score, "block": None}
    await run.save()
    b = blocks[target]
    return {"run_id": str(run.id), "finished": False, "score": None,
            "block": {k: v for k, v in b.items() if k not in ("score", "condition")}}


@router.get("/quests/{quest_id}/stats")
async def quest_stats(quest_id: str, user: dict = Depends(require_role("teacher", "admin"))):
    q = await _get_quest(quest_id)
    _ensure_can_manage(q, user)
    runs = await QuestRun.find(QuestRun.quest_id == quest_id).to_list()
    started = len(runs)
    finished = sum(1 for r in runs if r.finished)
    scores = [r.score for r in runs if r.finished]
    durations = [ (r.finished_at - r.started_at).total_seconds()
                  for r in runs if r.finished and r.finished_at ]
    # стартовый блок засчитан всем, дальше — по факту попадания в trace
    trace_ids = [set(step.get("block_id") for step in r.trace) for r in runs]
    funnel = []
    for b in q.structure["blocks"]:
        reached = sum(1 for ids in trace_ids if b["id"] in ids)
        if b is q.structure["blocks"][0]:
            reached = started
        funnel.append({"block_id": b["id"], "type": b["type"], "reached": reached})
    return {"runs": started, "finished": finished,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            "avg_duration_sec": round(sum(durations) / len(durations)) if durations else None,
            "funnel": funnel}
