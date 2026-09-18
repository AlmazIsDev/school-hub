import secrets

from ..core.redis import get_redis

r = get_redis()

CODE_TTL = 900


async def issue_code(user_id: str) -> str:
    code = f"{secrets.randbelow(900000) + 100000}"
    await r.set(f"vkcode:{code}", user_id, ex=CODE_TTL)
    return code


async def consume_code(code: str) -> str | None:
    return await r.getdel(f"vkcode:{code}")
