import secrets

import jwt
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
from fastapi import APIRouter, Depends, HTTPException
from ...core import redis as core_redis
from ...core.auth import verify_password, make_tokens, decode_token, hash_password
from ...core.security import get_current_user, require_role
from . import service, schemas
from .models import SchoolClass, User

router = APIRouter(prefix="/api")

@router.post("/auth/login", response_model=schemas.TokensOut)
async def login(body: schemas.LoginIn):
    user = await service.by_login(body.login)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    return {**make_tokens(user.id, user.role), "must_change_password": user.password_temp}

@router.post("/auth/refresh", response_model=schemas.TokensOut)
async def refresh(body: schemas.RefreshIn):
    try:
        p = decode_token(body.refresh)
        if p["type"] != "refresh":
            raise HTTPException(401, "Нужен refresh-токен")
        user_id = p["sub"]
    except HTTPException:
        raise
    except (jwt.InvalidTokenError, KeyError, TypeError):
        raise HTTPException(401, "Токен невалиден")
    user = await service.by_id(user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    return {**make_tokens(user.id, user.role), "must_change_password": user.password_temp}

@router.post("/auth/first-password")
async def first_password(body: schemas.FirstPasswordIn, user: dict = Depends(get_current_user)):
    if len(body.new_password) < 8:
        raise HTTPException(422, "Минимум 8 символов")
    u = await service.by_id(user["id"])
    if not u:
        raise HTTPException(401, "Пользователь не найден")
    u.password_hash, u.password_temp = hash_password(body.new_password), False
    await u.save()
    return {"ok": True}

@router.post("/users")
async def create_user(body: schemas.UserCreateIn, user: dict = Depends(require_role("admin"))):
    if body.role not in ("student", "teacher", "admin"):
        raise HTTPException(422, "Роль не в списке")
    if await service.by_login(body.login):
        raise HTTPException(409, f"Логин «{body.login}» занят")
    try:
        _, temp = await service.create_user(**body.model_dump())
    except DuplicateKeyError as err:
        # mongomock индексы не эмулирует, реальный Mongo отсекает гонку;
        # какой именно индекс споткнулся — видно в сообщении (login/vk_id)
        raise HTTPException(409, f"Конфликт уникальности: {err.details.get('keyPattern', 'логин занят')}")
    return {"ok": True, "temp_password": temp}

@router.get("/users")
async def list_users(user: dict = Depends(require_role("admin", "teacher"))):
    rows = await User.find_all().to_list()
    return [{"id": str(u.id), "login": u.login, "full_name": u.full_name, "role": u.role,
             "class_id": u.class_id, "vk_id": u.vk_id} for u in rows]


async def _get_user_or_404(user_id: str) -> User:
    u = await service.by_id(user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    return u


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: schemas.UserPatchIn,
                     user: dict = Depends(require_role("admin"))):
    u = await _get_user_or_404(user_id)
    data = body.model_dump(exclude_unset=True)
    if "class_id" in data and data["class_id"] is not None:
        if not await SchoolClass.get(ObjectId(data["class_id"])):
            raise HTTPException(404, "Класс не найден")
    for field, value in data.items():
        setattr(u, field, value)
    try:
        await u.save()
    except DuplicateKeyError:
        raise HTTPException(409, "Такой vk уже привязан к другому аккаунту")
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(require_role("admin"))):
    u = await _get_user_or_404(user_id)
    if str(u.id) == user["id"]:
        raise HTTPException(409, "Нельзя удалить самого себя")
    await u.delete()
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, user: dict = Depends(require_role("admin"))):
    u = await _get_user_or_404(user_id)
    temp = secrets.token_urlsafe(9)
    u.password_hash, u.password_temp = hash_password(temp), True
    await u.save()
    return {"temp_password": temp}


@router.delete("/users/{user_id}/vk")
async def admin_unlink_vk(user_id: str, user: dict = Depends(require_role("admin"))):
    u = await _get_user_or_404(user_id)
    u.vk_id = None
    await u.save()
    return {"ok": True}


@router.delete("/classes/{class_id}")
async def delete_class(class_id: str, user: dict = Depends(require_role("admin"))):
    try:
        oid = ObjectId(class_id)
    except (InvalidId, TypeError):
        raise HTTPException(404, "Класс не найден")
    cls = await SchoolClass.get(oid)
    if not cls:
        raise HTTPException(404, "Класс не найден")
    if await User.find_one(User.class_id == class_id):
        raise HTTPException(409, "В классе есть ученики — сначала переведи их")
    await cls.delete()
    return {"ok": True}

@router.post("/classes")
async def create_class(body: schemas.ClassIn, user: dict = Depends(require_role("admin"))):
    await SchoolClass(**body.model_dump()).insert()
    return {"ok": True}

@router.get("/classes")
async def list_classes(user: dict = Depends(get_current_user)):
    rows = await SchoolClass.find_all().to_list()
    return [{"id": str(c.id), "grade": c.grade, "letter": c.letter} for c in rows]


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    u = await service.by_id(user["id"])
    if not u:
        raise HTTPException(401, "Пользователь не найден")
    return {"id": str(u.id), "login": u.login, "full_name": u.full_name, "role": u.role,
            "class_id": u.class_id, "vk_id": u.vk_id}


@router.post("/me/vk-code")
async def me_vk_code(user: dict = Depends(get_current_user)):
    code = f"{secrets.randbelow(900000) + 100000}"
    await core_redis.get_redis().set(f"vkcode:{code}", user["id"], ex=900)
    return {"code": code}


@router.delete("/me/vk")
async def me_vk_unlink(user: dict = Depends(get_current_user)):
    u = await service.by_id(user["id"])
    if not u:
        raise HTTPException(401, "Пользователь не найден")
    u.vk_id = None
    await u.save()
    return {"ok": True}
