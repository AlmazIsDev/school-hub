import json

import pytest

from app.core import events, redis as core_redis


class FakeRedis:
    def __init__(self):
        self.published: list[str] = []

    async def publish(self, channel, message):
        self.published.append(message)


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(core_redis, "get_redis", lambda: r)
    return r


async def test_publish_sends_json_with_type(fake_redis):
    await events.publish("poll.published", poll_id="123")
    data = json.loads(fake_redis.published[0])
    assert data == {"type": "poll.published", "poll_id": "123"}


async def test_dispatch_calls_subscribed_handler(fake_redis):
    seen = []
    events.subscribe("test.event", lambda payload, vk: seen.append((payload, vk)))
    try:
        await events.dispatch({"type": "test.event", "x": 1}, vk="vk")
    finally:
        events._subscribers.pop("test.event")
    assert seen == [({"type": "test.event", "x": 1}, "vk")]


async def test_handler_crash_does_not_kill_dispatch(fake_redis):
    seen = []

    async def boom(payload, vk):
        raise RuntimeError("упал")

    events.subscribe("test.event2", boom)
    events.subscribe("test.event2", lambda p, vk: seen.append(p))
    try:
        await events.dispatch({"type": "test.event2"}, vk=None)
    finally:
        events._subscribers.pop("test.event2")
    assert seen == [{"type": "test.event2"}]


async def test_publish_swallows_redis_failure(monkeypatch):
    class DeadRedis:
        async def publish(self, *a, **kw):
            raise ConnectionError()

    monkeypatch.setattr(core_redis, "get_redis", lambda: DeadRedis())
    await events.publish("poll.published", poll_id="1")  # не должно упасть
