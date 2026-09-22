import secrets

from bson import ObjectId
from beanie.operators import Eq

from ...core.auth import hash_password
from .models import User


async def create_user(*, school_id: str, login: str, full_name: str, role: str,
                      class_id: str | None = None):
    temp = secrets.token_urlsafe(9)
    u = User(school_id=school_id, login=login, full_name=full_name, role=role,
             class_id=class_id,
             password_hash=hash_password(temp), password_temp=True)
    await u.insert()
    return u, temp


async def by_login(school_id: str, login: str) -> User | None:
    return await User.find_one(Eq(User.school_id, school_id), Eq(User.login, login))


async def ensure_superadmin(*, login: str, password: str, full_name: str) -> None:
    """Платформенный админ из .env. Создаётся один раз, пароль сразу постоянный."""
    if not password:
        return
    existing = await User.find_one(User.role == "superadmin")
    if existing:
        return
    u = User(school_id=None, login=login, full_name=full_name, role="superadmin",
             password_hash=hash_password(password), password_temp=False)
    await u.insert()


async def by_vk(vk_id: int) -> User | None:
    return await User.find_one(User.vk_id == vk_id)


async def by_id(user_id: str) -> User | None:
    """id приходит из JWT (sub) или из Redis — может быть любым мусором, не кидаем исключение."""
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    return await User.get(oid)
