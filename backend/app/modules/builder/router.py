from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException

from ...core.security import get_current_user, require_role
from ...modules.users.models import SchoolClass, User
from . import schemas
from .models import Quest

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
    if user["role"] == "student":
        me = await User.get(ObjectId(user["id"]))
        if not me or q.class_id != me.class_id:
            raise HTTPException(403, "Квест другого класса")
    # ученик не должен видеть score и condition — вырезаем
    blocks = [{k: v for k, v in b.items() if k not in ("score", "condition")}
              for b in q.structure["blocks"]]
    return {"id": str(q.id), "title": q.title, "blocks": blocks}
