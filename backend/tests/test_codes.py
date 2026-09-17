import fakeredis.aioredis as fr

from app.bot import codes


async def test_issue_and_consume(monkeypatch):
    codes.r = fr.FakeRedis()
    c = await codes.issue_code(user_id=7)
    assert await codes.consume_code(c) == 7
    assert await codes.consume_code(c) is None  # одноразовый


async def test_expired_or_unknown_code():
    codes.r = fr.FakeRedis()
    assert await codes.consume_code("999999") is None
