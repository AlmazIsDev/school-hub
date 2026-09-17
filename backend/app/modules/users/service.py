import secrets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import User
from ...core.auth import hash_password

def create_user(session: AsyncSession, *, login: str, full_name: str, role: str, class_id: int | None = None):
    temp = secrets.token_urlsafe(9)
    u = User(login=login, full_name=full_name, role=role, class_id=class_id,
             password_hash=hash_password(temp), password_temp=True)
    session.add(u)
    return u, temp

async def by_login(session: AsyncSession, login: str) -> User | None:
    return (await session.execute(select(User).where(User.login == login))).scalar_one_or_none()
