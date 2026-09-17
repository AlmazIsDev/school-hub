import secrets

import redis.asyncio as aioredis

from ..core.config import settings

r = aioredis.from_url(settings.redis_url, decode_responses=True)

CODE_TTL = 900


async def issue_code(user_id: int) -> str:
    code = f"{secrets.randbelow(900000) + 100000}"
    await r.set(f"vkcode:{code}", user_id, ex=CODE_TTL)
    return code


async def consume_code(code: str) -> int | None:
    val = await r.getdel(f"vkcode:{code}")
    return int(val) if val else None
