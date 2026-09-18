import re

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException

from ...core.security import get_current_user, require_role
from . import schemas
from .models import Building, Floor, Room

router = APIRouter(prefix="/api/nav", tags=["navigator"])


def _get(doc_id: str):
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Не найдено")


# ---------- buildings ----------

@router.post("/buildings")
async def create_building(body: schemas.BuildingIn, user: dict = Depends(require_role("admin"))):
    b = Building(name=body.name, address=body.address)
    await b.insert()
    return {"id": str(b.id), "name": b.name, "address": b.address, "created_at": b.created_at}


@router.get("/buildings")
async def list_buildings(user: dict = Depends(get_current_user)):
    return [{"id": str(b.id), "name": b.name, "address": b.address, "created_at": b.created_at}
            for b in await Building.find_all().to_list()]


@router.delete("/buildings/{building_id}")
async def delete_building(building_id: str, user: dict = Depends(require_role("admin"))):
    b = await Building.get(_get(building_id))
    if not b:
        raise HTTPException(404, "Здание не найдено")
    floors = await Floor.find(Floor.building_id == building_id).to_list()
    if floors:
        # каскад: этажи с комнатами снесём вместе со зданием
        floor_ids = [str(f.id) for f in floors]
        await Room.find({"floor_id": {"$in": floor_ids}}).delete()
        for f in floors:
            await f.delete()
    await b.delete()
    return {"ok": True}


# ---------- floors ----------

@router.post("/floors")
async def create_floor(body: schemas.FloorIn, user: dict = Depends(require_role("admin"))):
    if not await Building.get(_get(body.building_id)):
        raise HTTPException(404, "Здание не найдено")
    f = Floor(building_id=body.building_id, level=body.level)
    await f.insert()
    return {"id": str(f.id), "building_id": f.building_id, "level": f.level, "plan_id": f.plan_id}


@router.get("/floors")
async def list_floors(building_id: str, user: dict = Depends(get_current_user)):
    if not await Building.get(_get(building_id)):
        raise HTTPException(404, "Здание не найдено")
    floors = await Floor.find(Floor.building_id == building_id).sort("level").to_list()
    return [{"id": str(f.id), "building_id": f.building_id, "level": f.level, "plan_id": f.plan_id}
            for f in floors]


@router.delete("/floors/{floor_id}")
async def delete_floor(floor_id: str, user: dict = Depends(require_role("admin"))):
    f = await Floor.get(_get(floor_id))
    if not f:
        raise HTTPException(404, "Этаж не найден")
    if await Room.find_one(Room.floor_id == floor_id):
        raise HTTPException(409, "На этаже есть комнаты, сначала удали их")
    await f.delete()
    return {"ok": True}


# ---------- rooms ----------

def _room_out(r: Room) -> dict:
    return {"id": str(r.id), "floor_id": r.floor_id, "number": r.number,
            "name": r.name, "geometry": r.geometry.model_dump()}


@router.post("/rooms")
async def create_room(body: schemas.RoomIn, user: dict = Depends(require_role("admin"))):
    if not await Floor.get(_get(body.floor_id)):
        raise HTTPException(404, "Этаж не найден")
    r = Room(floor_id=body.floor_id, number=body.number, name=body.name, geometry=body.geometry)
    await r.insert()
    return _room_out(r)


@router.get("/rooms")
async def list_rooms(floor_id: str, user: dict = Depends(get_current_user)):
    if not await Floor.get(_get(floor_id)):
        raise HTTPException(404, "Этаж не найден")
    return [_room_out(r) for r in await Room.find(Room.floor_id == floor_id).to_list()]


@router.put("/rooms/{room_id}")
async def update_room(room_id: str, body: schemas.RoomIn, user: dict = Depends(require_role("admin"))):
    r = await Room.get(_get(room_id))
    if not r:
        raise HTTPException(404, "Комната не найдена")
    if body.floor_id != r.floor_id and not await Floor.get(_get(body.floor_id)):
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
    if not r:
        raise HTTPException(404, "Комната не найдена")
    await r.delete()
    return {"ok": True}


# ---------- search ----------

@router.get("/search")
async def search_rooms(q: str, user: dict = Depends(get_current_user)):
    q = q.strip()
    if not q:
        raise HTTPException(422, "Пустой запрос")
    rooms = await Room.find(
        {"number": {"$regex": f"^{re.escape(q)}", "$options": "i"}}
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
