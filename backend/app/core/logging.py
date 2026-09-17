import json, logging, time, uuid
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname, "logger": record.name,
            "msg": record.getMessage(), "request_id": request_id.get(),
        }, ensure_ascii=False)

def setup_logging():
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    logging.root.handlers = [h]
    logging.root.level = logging.INFO

def log_request(user_id, duration_ms):
    logging.getLogger("api").info("request", extra={"user_id": user_id})
