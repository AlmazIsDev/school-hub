import pytest
from fastapi import HTTPException

from app.core.auth import decode_token, hash_password, make_tokens, verify_password
from app.core.security import require_role


def test_password_roundtrip():
    h = hash_password("pw")
    assert verify_password("pw", h) and not verify_password("x", h)


def test_tokens():
    t = make_tokens(user_id=1, role="teacher", school_id="s1")
    at = decode_token(t["access"])
    assert at["sub"] == "1" and at["role"] == "teacher" and at["type"] == "access"
    assert decode_token(t["refresh"])["type"] == "refresh"


async def test_role_guard():
    dep = require_role("teacher")
    with pytest.raises(HTTPException) as e:
        await dep(user=type("U", (), {"role": "student"})())
    assert e.value.status_code == 403
