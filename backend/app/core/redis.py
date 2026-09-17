import redis.asyncio as aioredis

from .config import settings

_client = None


def get_redis():
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client
