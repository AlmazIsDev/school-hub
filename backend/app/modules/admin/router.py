"""Прямое управление БД для админа: просмотр/правка/создание/удаление документов.

Формат обмена - MongoDB Extended JSON (json_util): _id и даты ходят как
{"$oid": ...} / {"$date": ...} и обратно парсятся тем же json_util. Системные
коллекции (system.*, fs.*) закрыты.
"""
import json
import re
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from bson import json_util
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.db import get_motor_client
from ...core.security import require_role

router = APIRouter(prefix="/api/admin/db", tags=["admin"])


async def _collection(name: str):
    db = get_motor_client().get_database()
    if name not in await db.list_collection_names():
        raise HTTPException(404, "Коллекция не найдена")
    return db[name]


def _collection_unchecked(name: str) -> Any:
    """Коллекция без проверки существования (для ленивого создания)."""
    if name.startswith(("system.", "fs.")) or not re.fullmatch(r"[\w.-]+", name):
        raise HTTPException(404, "Коллекция не найдена")
    return get_motor_client().get_database()[name]


def _oid(doc_id: str) -> ObjectId:
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Документ не найден")


async def _search_query(col, q: str) -> dict:
    """«поле: значение» - точный матч поля (значение парсится как Extended JSON);
    иначе - case-insensitive regex по строковым полям (берём из образца документа)."""
    q = (q or "").strip()
    if not q:
        return {}
    m = re.match(r"^([\w.]+)\s*:\s*(.+)$", q)
    if m:
        field, value = m.group(1), m.group(2)
        try:
            return {field: json_util.loads(value)}
        except Exception:
            return {field: value}
    sample = await col.find_one()
    fields = [f for f in sample.keys() if f != "_id"] if sample else []
    return {"$or": [{f: {"$regex": re.escape(q), "$options": "i"}} for f in fields]}


@router.get("/collections")
async def list_collections(user: dict = Depends(require_role("admin"))):
    db = get_motor_client().get_database()
    names = sorted(n for n in await db.list_collection_names()
                   if not n.startswith(("system.", "fs.")))
    return [{"name": n, "count": await db[n].count_documents({})} for n in names]


@router.get("/{name}/docs")
async def list_docs(name: str,
                    q: str = "",
                    skip: int = Query(0, ge=0),
                    limit: int = Query(50, ge=1, le=100),
                    sort: str = "",
                    order: int = Query(-1, ge=-1, le=1),
                    user: dict = Depends(require_role("admin"))):
    col = await _collection(name)
    flt = await _search_query(col, q)
    total = await col.count_documents({})  # total без поиска - как в TradeVerse
    cursor = col.find(flt).skip(skip).limit(limit)
    if sort:
        cursor = cursor.sort([(sort, order)])
    docs = [json.loads(json_util.dumps(d)) for d in await cursor.to_list(limit)]
    return {"items": docs, "total": total, "has_more": len(docs) == limit}


@router.post("/{name}")
async def create_doc(name: str, body: dict, user: dict = Depends(require_role("admin"))):
    # коллекция может не существовать - insert её лениво создаст
    col = _collection_unchecked(name)
    try:
        result = await col.insert_one(json_util.loads(json.dumps(body)))
    except Exception as err:
        raise HTTPException(422, f"Не удалось вставить документ: {err}")
    return {"id": str(result.inserted_id)}


@router.put("/{name}/{doc_id}")
async def update_doc(name: str, doc_id: str, body: dict,
                     user: dict = Depends(require_role("admin"))):
    col = await _collection(name)
    try:
        doc = json_util.loads(json.dumps(body))
    except Exception as err:
        raise HTTPException(422, f"Невалидный документ: {err}")
    doc.pop("_id", None)  # _id не меняем
    try:
        result = await col.replace_one({"_id": _oid(doc_id)}, doc)
    except Exception as err:
        raise HTTPException(422, f"Не удалось сохранить: {err}")
    if result.matched_count == 0:
        raise HTTPException(404, "Документ не найден")
    return {"ok": True}


@router.delete("/{name}/{doc_id}")
async def delete_doc(name: str, doc_id: str, user: dict = Depends(require_role("admin"))):
    col = await _collection(name)
    result = await col.delete_one({"_id": _oid(doc_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Документ не найден")
    return {"ok": True}
