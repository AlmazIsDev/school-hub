"""CRUD школ — только superadmin. Школьный админ создаётся вместе со школой."""
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.auth import hash_password
from ...core.security import require_role
from ..users.models import School, User

router = APIRouter(prefix="/api/schools", tags=["schools"])


class SchoolIn(BaseModel):
    name: str
    code: str
    admin_login: str
    admin_full_name: str


@router.post("")
async def create_school(body: SchoolIn, user: dict = Depends(require_role("admin"))):
    code = body.code.strip().lower()
    if not (2 <= len(code) <= 32) or not code.replace("-", "").isalnum():
        raise HTTPException(422, "Код школы: 2-32 символа, буквы/цифры/дефис")
    if await School.find_one(School.code == code):
        raise HTTPException(409, "Код школы уже занят")
    school = School(name=body.name.strip(), code=code)
    await school.insert()
    temp = secrets.token_urlsafe(9)
    await User(school_id=str(school.id), login=body.admin_login.strip(),
               full_name=body.admin_full_name.strip(), role="admin",
               password_hash=hash_password(temp), password_temp=True).insert()
    return {"id": str(school.id), "code": code, "admin_temp_password": temp}


@router.get("")
async def list_schools(user: dict = Depends(require_role("admin"))):
    return [{"id": str(s.id), "name": s.name, "code": s.code} for s in await School.find_all().to_list()]


@router.delete("/{school_id}")
async def delete_school(school_id: str, user: dict = Depends(require_role("admin"))):
    try:
        oid = ObjectId(school_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Школа не найдена")
    school = await School.get(oid)
    if not school:
        raise HTTPException(404, "Школа не найдена")
    await school.delete()
    return {"ok": True}
