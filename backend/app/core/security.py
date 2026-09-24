import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_token

bearer = HTTPBearer(auto_error=False)

SUPERADMIN = "superadmin"


def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                     request: Request = None) -> dict:
    if not cred:
        raise HTTPException(401, "Не авторизован")
    try:
        payload = decode_token(cred.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Токен невалиден")
    if payload.get("type") != "access":
        raise HTTPException(401, "Нужен access-токен")
    user = {
        "id": payload["sub"],
        "role": payload["role"],
        # старые токены без school_id - до логина повторно
        "school_id": payload.get("school_id"),
    }
    # superadmin работает в контексте выбранной школы (фронт шлёт X-School-Id); без него он видит только платформенные разделы. Кривой id даёт пустые выборки, чужих данных не достать - отдельная проверка School не нужна.
    if user["role"] == SUPERADMIN and request is not None:
        sid = request.headers.get("X-School-Id", "")
        try:
            user["school_id"] = str(ObjectId(sid))
        except Exception:
            pass
    return user


def require_role(*roles):
    """Гвард роли; superadmin проходит любую проверку."""
    async def guard(user: dict = Depends(get_current_user)):
        role = user["role"] if isinstance(user, dict) else user.role
        if role != SUPERADMIN and role not in roles:
            raise HTTPException(403, "Недостаточно прав")
        return user

    return guard
