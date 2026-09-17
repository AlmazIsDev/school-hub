import logging
import re


class Dispatcher:
    def __init__(self):
        self._handlers = []

    def on(self, pattern: str):
        rx = re.compile(pattern, re.IGNORECASE)

        def deco(fn):
            self._handlers.append((rx, fn))
            return fn

        return deco

    async def dispatch(self, event: dict):
        text = (event.get("text") or "").strip()
        for rx, fn in self._handlers:
            m = rx.match(text)
            if m:
                try:
                    await fn({**event, "match": m}, event.get("vk"))
                except Exception:
                    logging.getLogger("bot").exception("handler %s failed", fn.__name__)
                return
