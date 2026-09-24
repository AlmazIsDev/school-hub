import re

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from gridfs import NoFile

from ...core.db import get_gridfs
from ...core.security import get_current_user, require_role
from . import schemas
from .models import Building, Floor, Room

router = APIRouter(prefix="/api/nav", tags=["navigator"])

ALLOWED_PLAN_TYPES = {"image/svg+xml", "image/png", "image/jpeg"}
MAX_PLAN_SIZE = 5 * 1024 * 1024


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


# ---------- buildings ----------

@router.post("/buildings")
async def create_building(body: schemas.BuildingIn, user: dict = Depends(require_role("admin"))):
    b = Building(school_id=_school(user), name=body.name, address=body.address)
    await b.insert()
    return {"id": str(b.id), "name": b.name, "address": b.address, "created_at": b.created_at}


@router.get("/buildings")
async def list_buildings(user: dict = Depends(get_current_user)):
    return [{"id": str(b.id), "name": b.name, "address": b.address, "created_at": b.created_at}
            for b in await Building.find(Building.school_id == _school(user)).to_list()]


@router.delete("/buildings/{building_id}")
async def delete_building(building_id: str, user: dict = Depends(require_role("admin"))):
    b = await Building.get(_get(building_id))
    if not b or b.school_id != _school(user):
        raise HTTPException(404, "Здание не найдено")
    floors = await Floor.find(Floor.building_id == building_id).to_list()
    if floors:
        # каскад: этажи с комнатами снесём вместе со зданием ponytail: без транзакции (нужен replica set) - здание удаляем последним, сироты при сбое halfway не видны в поиске по живому зданию
        floor_ids = [str(f.id) for f in floors]
        await Room.find({"floor_id": {"$in": floor_ids}}).delete()
        for f in floors:
            await _delete_plan(f.plan_id)
            await f.delete()
    await b.delete()
    return {"ok": True}


@router.patch("/buildings/{building_id}")
async def patch_building(building_id: str, body: schemas.BuildingPatchIn,
                         user: dict = Depends(require_role("admin"))):
    b = await Building.get(_get(building_id))
    if not b or b.school_id != _school(user):
        raise HTTPException(404, "Здание не найдено")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(b, field, value)
    await b.save()
    return {"id": str(b.id), "name": b.name, "address": b.address, "created_at": b.created_at}


# ---------- floors ----------

@router.post("/floors")
async def create_floor(body: schemas.FloorIn, user: dict = Depends(require_role("admin"))):
    b = await Building.get(_get(body.building_id))
    if not b or b.school_id != _school(user):
        raise HTTPException(404, "Здание не найдено")
    if await Floor.find_one(Floor.building_id == body.building_id, Floor.level == body.level):
        raise HTTPException(409, "Этаж с таким уровнем уже есть")
    f = Floor(school_id=_school(user), building_id=body.building_id, level=body.level)
    await f.insert()
    return {"id": str(f.id), "building_id": f.building_id, "level": f.level, "plan_id": f.plan_id}


@router.get("/floors")
async def list_floors(building_id: str, user: dict = Depends(get_current_user)):
    b = await Building.get(_get(building_id))
    if not b or b.school_id != _school(user):
        raise HTTPException(404, "Здание не найдено")
    floors = await Floor.find(Floor.building_id == building_id).sort("level").to_list()
    return [{"id": str(f.id), "building_id": f.building_id, "level": f.level, "plan_id": f.plan_id}
            for f in floors]


async def _delete_plan(plan_id: str | None) -> None:
    """Файл из GridFS, отсутствие файла молча игнорируем."""
    if not plan_id:
        return
    try:
        await get_gridfs().delete(ObjectId(plan_id))
    except NoFile:
        pass


@router.delete("/floors/{floor_id}")
async def delete_floor(floor_id: str, user: dict = Depends(require_role("admin"))):
    f = await Floor.get(_get(floor_id))
    if not f or f.school_id != _school(user):
        raise HTTPException(404, "Этаж не найден")
    if await Room.find_one(Room.floor_id == floor_id):
        raise HTTPException(409, "На этаже есть комнаты, сначала удали их")
    await _delete_plan(f.plan_id)
    await f.delete()
    return {"ok": True}


@router.post("/floors/{floor_id}/plan")
async def upload_plan(floor_id: str, file: UploadFile = File(...),
                      user: dict = Depends(require_role("admin"))):
    f = await Floor.get(_get(floor_id))
    if not f or f.school_id != _school(user):
        raise HTTPException(404, "Этаж не найден")
    if file.content_type not in ALLOWED_PLAN_TYPES:
        raise HTTPException(422, "Разрешены только SVG, PNG и JPEG")
    data = await file.read()
    if len(data) > MAX_PLAN_SIZE:
        raise HTTPException(413, "Файл больше 5 МБ")
    if not data:
        raise HTTPException(422, "Пустой файл")
    # план неизменяем: новая загрузка = новый plan_id, старый файл подчищаем
    await _delete_plan(f.plan_id)
    grid = get_gridfs()
    fid = await grid.upload_from_stream(file.filename or "plan", data,
                                        metadata={"content_type": file.content_type})
    f.plan_id = str(fid)
    await f.save()
    return {"id": str(f.id), "plan_id": f.plan_id}


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str, user: dict = Depends(get_current_user)):
    try:
        grid_out = await get_gridfs().open_download_stream(_get(plan_id))
    except NoFile:
        raise HTTPException(404, "План не найден")
    content = await grid_out.read()
    content_type = (grid_out.metadata or {}).get("content_type", "application/octet-stream")
    # attachment + sandbox: SVG может содержать script - не даём ему исполниться в origin
    ext = content_type.split("/")[-1].replace("svg+xml", "svg").replace("jpeg", "jpg")
    return Response(
        content=content, media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="plan-{plan_id}.{ext}"',
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "public, max-age=31536000, immutable",
        })


# ---------- rooms ----------

def _room_out(r: Room) -> dict:
    return {"id": str(r.id), "floor_id": r.floor_id, "number": r.number,
            "name": r.name, "geometry": r.geometry.model_dump()}


@router.post("/rooms")
async def create_room(body: schemas.RoomIn, user: dict = Depends(require_role("admin"))):
    f = await Floor.get(_get(body.floor_id))
    if not f or f.school_id != _school(user):
        raise HTTPException(404, "Этаж не найден")
    r = Room(school_id=f.school_id, floor_id=body.floor_id, number=body.number,
             name=body.name, geometry=body.geometry)
    await r.insert()
    return _room_out(r)


@router.get("/rooms")
async def list_rooms(floor_id: str, user: dict = Depends(get_current_user)):
    f = await Floor.get(_get(floor_id))
    if not f or f.school_id != _school(user):
        raise HTTPException(404, "Этаж не найден")
    return [_room_out(r) for r in await Room.find(Room.floor_id == floor_id).to_list()]


@router.put("/rooms/{room_id}")
async def update_room(room_id: str, body: schemas.RoomIn, user: dict = Depends(require_role("admin"))):
    r = await Room.get(_get(room_id))
    if not r or r.school_id != _school(user):
        raise HTTPException(404, "Комната не найдена")
    target_floor = await Floor.get(_get(body.floor_id))
    if not target_floor or target_floor.school_id != _school(user):
        raise HTTPException(404, "Этаж не найден")
    r.floor_id = body.floor_id
    r.number = body.number
    r.name = body.name
    r.geometry = body.geometry
    await r.save()
    return _room_out(r)


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str, user: dict = Depends(require_role("admin"))):
    r = await Room.get(_get(room_id))
    if not r or r.school_id != _school(user):
        raise HTTPException(404, "Комната не найдена")
    await r.delete()
    return {"ok": True}


# ---------- search ----------

@router.get("/search")
async def search_rooms(q: str, user: dict = Depends(get_current_user)):
    q = q.strip()
    if not q:
        raise HTTPException(422, "Пустой запрос")
    if len(q) > 64:
        raise HTTPException(422, "Слишком длинный запрос")
    rooms = await Room.find(
        {"school_id": _school(user),
         "number": {"$regex": f"^{re.escape(q)}", "$options": "i"}}
    ).limit(20).to_list()
    if not rooms:
        return []
    floor_ids = {r.floor_id for r in rooms}
    floors = {str(f.id): f for f in await Floor.find({"_id": {"$in": [_get(i) for i in floor_ids]}}).to_list()}
    out = []
    for r in rooms:
        f = floors.get(r.floor_id)
        out.append({"id": str(r.id), "number": r.number, "name": r.name,
                    "floor_id": r.floor_id, "building_id": f.building_id if f else None})
    return out
