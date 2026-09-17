import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Не авторизован")
    try:
        payload = decode_token(cred.credentials)
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Токен невалиден")
    if payload.get("type") != "access":
        raise HTTPException(401, "Нужен access-токен")
    return {"id": int(payload["sub"]), "role": payload["role"]}


def require_role(*roles):
    async def guard(user: dict = Depends(get_current_user)):
        # ponytail: принимаем и dict из get_current_user, и объект с .role (в тестах)
        role = user["role"] if isinstance(user, dict) else user.role
        if role not in roles:
            raise HTTPException(403, "Недостаточно прав")
        return user

    return guard
