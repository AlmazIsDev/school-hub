import asyncio
import logging

from ..core.config import settings
from .client import VKClient


def _log():
    return logging.getLogger("bot")


async def run_forever(client: VKClient, dp):
    backoff = 1
    while True:
        try:
            lp = await client.call("groups.getLongPollServer", group_id=settings.vk_group_id)
            ts = lp["ts"]
            backoff = 1
            while True:
                # Long Poll-запрос идёт напрямую на lp["server"], без access_token
                data = (
                    await client._http.get(
                        lp["server"],
                        params={"act": "a_check", "key": lp["key"], "ts": ts, "wait": 25},
                    )
                ).json()
                if "failed" in data:
                    if data["failed"] in (2, 3):
                        break  # ключ/сервер протух, пересоздаём
                    ts = data.get("ts", ts)
                    continue
                ts = data["ts"]
                for upd in data.get("updates", []):
                    if upd["type"] == "message_new":
                        msg = upd["object"]["message"]
                        await dp.dispatch(
                            {
                                "text": msg["text"],
                                "vk_user_id": msg["from_id"],
                                "peer_id": msg["peer_id"],
                                "vk": client,
                            }
                        )
        except Exception:
            _log().exception("longpoll crashed, reconnect in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
