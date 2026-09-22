import asyncio
import logging
import time

import httpx

from ..core.config import settings

API = "https://api.vk.com/method/"
V = "5.199"
RATE = 18  # rps на токен; лимит VK 20/сек, запас на вызовы вне messages.send


class VKClient:
    def __init__(self, token: str = ""):
        self.token = token or settings.vk_token
        self._stamps: list[float] = []
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(timeout=10)

    async def _throttle(self):
        async with self._lock:
            now = time.monotonic()
            self._stamps = [t for t in self._stamps if now - t < 1]
            if len(self._stamps) >= RATE:
                await asyncio.sleep(1 - (now - self._stamps[0]))
            self._stamps.append(time.monotonic())

    async def call(self, method: str, **params) -> dict:
        params.update(access_token=self.token, v=V)
        delay = 0.5
        for attempt in range(3):
            await self._throttle()
            resp = (await self._http.post(API + method, data=params)).json()
            if "error" not in resp:
                return resp["response"]
            err = resp["error"].get("error_code")
            logging.getLogger("bot").warning("vk %s error %s", method, err)
            if err == 6:  # rate limit
                delay = max(delay, 1.0)
            await asyncio.sleep(delay)
            delay *= 4
        raise RuntimeError(f"VK {method} failed after retries: {resp['error']}")
