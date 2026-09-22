import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import settings

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, h: str) -> bool:
    try:
        return _ph.verify(h, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _token(user_id: int, role: str, school_id: str, typ: str, ttl: int) -> str:
    return jwt.encode(
        {"sub": str(user_id), "role": role, "school_id": school_id,
         "type": typ, "exp": time.time() + ttl},
        settings.jwt_secret,
        settings.jwt_alg,
    )


def make_tokens(user_id: int, role: str, school_id: str) -> dict:
    return {
        "access": _token(user_id, role, school_id, "access", settings.access_ttl_min * 60),
        "refresh": _token(user_id, role, school_id, "refresh", settings.refresh_ttl_days * 86400),
    }


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
