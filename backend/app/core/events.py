"""Единый pub/sub событий: издатель и подписчики на канале redis "events".

Redis pub/sub не персистентен: событие, ушедшее пока подписчика не было,
теряется. Поэтому у рассылок (poll, media) есть догонялки при старте бота.
"""
import asyncio
import json
import logging

from . import redis as core_redis

log = logging.getLogger("bot")

CHANNEL = "events"

_subscribers: dict[str, list] = {}


def subscribe(event_type: str, handler):
    """handler(payload: dict, vk) - регистрируется в app.bot.__main__."""
    _subscribers.setdefault(event_type, []).append(handler)


async def publish(type_: str, **data):
    try:
        await core_redis.get_redis().publish(
            CHANNEL, json.dumps({"type": type_, **data}, ensure_ascii=False))
    except Exception:
        # падение pub/sub не должно ломать основную операцию - подписчик потеряет событие, догонялка доставит
        log.warning("%s не опубликован: %s", type_, data)


async def dispatch(data: dict, vk):
    for handler in _subscribers.get(data.get("type"), []):
        try:
            await handler(data, vk)
        except Exception:
            log.exception("обработчик %s упал на %s",
                          handler.__qualname__, data.get("type"))


async def listen(vk):
    """Подписка на канал, переживает недоступный redis."""
    while True:
        try:
            pubsub = core_redis.get_redis().pubsub()
            await pubsub.subscribe(CHANNEL)
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                except (ValueError, TypeError):
                    continue
                await dispatch(data, vk)
        except Exception:
            log.exception("events listener crashed, reconnect in 5s")
            await asyncio.sleep(5)
