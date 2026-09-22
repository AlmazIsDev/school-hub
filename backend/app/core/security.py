import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_token

bearer = HTTPBearer(auto_error=False)

SUPERADMIN = "superadmin"


def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Не авторизован")
    try:
        payload = decode_token(cred.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Токен невалиден")
    if payload.get("type") != "access":
        raise HTTPException(401, "Нужен access-токен")
    return {
        "id": payload["sub"],
        "role": payload["role"],
        # старые токены без school_id — до логина повторно
        "school_id": payload.get("school_id"),
    }


def require_role(*roles):
    """Гвард роли; superadmin проходит любую проверку."""
    async def guard(user: dict = Depends(get_current_user)):
        role = user["role"] if isinstance(user, dict) else user.role
        if role != SUPERADMIN and role not in roles:
            raise HTTPException(403, "Недостаточно прав")
        return user

    return guard
