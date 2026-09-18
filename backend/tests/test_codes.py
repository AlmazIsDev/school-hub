import fakeredis.aioredis as fr

from app.bot import codes


async def test_issue_and_consume():
    codes.r = fr.FakeRedis(decode_responses=True)
    c = await codes.issue_code(user_id="6aad83299b1a82fc8cdc6365")
    assert await codes.consume_code(c) == "6aad83299b1a82fc8cdc6365"
    assert await codes.consume_code(c) is None  # одноразовый


async def test_expired_or_unknown_code():
    codes.r = fr.FakeRedis(decode_responses=True)
    assert await codes.consume_code("999999") is None
