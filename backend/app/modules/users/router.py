import secrets

import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ...core import redis as core_redis
from ...core.db import get_db
from ...core.auth import verify_password, make_tokens, decode_token, hash_password
from ...core.security import get_current_user, require_role
from . import service, schemas
from .models import User, SchoolClass

router = APIRouter(prefix="/api")

@router.post("/auth/login", response_model=schemas.TokensOut)
async def login(body: schemas.LoginIn, db: AsyncSession = Depends(get_db)):
    user = await service.by_login(db, body.login)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    return {**make_tokens(user.id, user.role), "must_change_password": user.password_temp}

@router.post("/auth/refresh", response_model=schemas.TokensOut)
async def refresh(body: schemas.RefreshIn, db: AsyncSession = Depends(get_db)):
    try:
        p = decode_token(body.refresh)
        if p["type"] != "refresh":
            raise HTTPException(401, "Нужен refresh-токен")
        user_id = int(p["sub"])
    except HTTPException:
        raise
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(401, "Токен невалиден")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    return {**make_tokens(user.id, user.role), "must_change_password": user.password_temp}

@router.post("/auth/first-password")
async def first_password(body: schemas.FirstPasswordIn, user: dict = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    if len(body.new_password) < 8:
        raise HTTPException(422, "Минимум 8 символов")
    u = await db.get(User, user["id"])
    if not u:
        raise HTTPException(401, "Пользователь не найден")
    u.password_hash, u.password_temp = hash_password(body.new_password), False
    await db.commit()
    return {"ok": True}

@router.post("/users")
async def create_user(body: schemas.UserCreateIn, user: dict = Depends(require_role("admin")),
                      db: AsyncSession = Depends(get_db)):
    if body.role not in ("student", "teacher", "admin"):
        raise HTTPException(422, "Роль не в списке")
    if await service.by_login(db, body.login):
        raise HTTPException(409, "Логин занят")
    _, temp = service.create_user(db, **body.model_dump())
    await db.commit()
    return {"ok": True, "temp_password": temp}

@router.get("/users")
async def list_users(user: dict = Depends(require_role("admin", "teacher")),
                     db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(User))).scalars().all()
    return [{"id": u.id, "login": u.login, "full_name": u.full_name, "role": u.role,
             "class_id": u.class_id, "vk_id": u.vk_id} for u in rows]

@router.post("/classes")
async def create_class(body: schemas.ClassIn, user: dict = Depends(require_role("admin")),
                       db: AsyncSession = Depends(get_db)):
    db.add(SchoolClass(**body.model_dump()))
    await db.commit()
    return {"ok": True}

@router.get("/classes")
async def list_classes(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SchoolClass))).scalars().all()
    return [{"id": c.id, "grade": c.grade, "letter": c.letter} for c in rows]


@router.post("/me/vk-code")
async def me_vk_code(user: dict = Depends(get_current_user)):
    code = f"{secrets.randbelow(900000) + 100000}"
    await core_redis.get_redis().set(f"vkcode:{code}", user["id"], ex=900)
    return {"code": code}


@router.delete("/me/vk")
async def me_vk_unlink(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    u = await db.get(User, user["id"])
    if not u:
        raise HTTPException(401, "Пользователь не найден")
    u.vk_id = None
    await db.commit()
    return {"ok": True}
