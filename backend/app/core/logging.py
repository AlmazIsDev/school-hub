import json, logging, uuid
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")

_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}

class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "level": record.levelname, "logger": record.name,
            "msg": record.getMessage(), "request_id": request_id.get(),
        }
        # extra-поля (user_id, duration_ms, ...) мержим в JSON как отдельные ключи
        data.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS})
        return json.dumps(data, ensure_ascii=False, default=str)

def setup_logging():
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    logging.root.handlers = [h]
    logging.root.level = logging.INFO
