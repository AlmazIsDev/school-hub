import secrets

from bson import ObjectId
from beanie.operators import Eq

from ...core.auth import hash_password
from .models import User


async def create_user(*, login: str, full_name: str, role: str, class_id: str | None = None):
    temp = secrets.token_urlsafe(9)
    u = User(login=login, full_name=full_name, role=role, class_id=class_id,
             password_hash=hash_password(temp), password_temp=True)
    await u.insert()
    return u, temp


async def by_login(login: str) -> User | None:
    return await User.find_one(Eq(User.login, login))


async def by_id(user_id: str) -> User | None:
    """id приходит из JWT (sub) или из Redis — может быть любым мусором, не кидаем исключение."""
    try:
        oid = ObjectId(user_id)
    except Exception:
        return None
    return await User.get(oid)
