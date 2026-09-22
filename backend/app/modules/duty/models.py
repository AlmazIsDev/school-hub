from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddedSlot(BaseModel):
    weekday: int  # 1..7, пн..вс
    slot: int  # 1..8
    user_id: str


class DutyZone(Document):
    school_id: str
    name: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "duty_zones"


class DutySchedule(Document):
    school_id: str
    teacher_id: str
    zone_id: str
    week_pattern: list[EmbeddedSlot]
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "duty_schedules"


class DutyCompletion(Document):
    school_id: str
    schedule_id: str
    weekday: int
    slot: int
    user_id: str
    date: datetime  # только дата, UTC, полночь
    marked_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "duty_completions"
        # защита от гонки двойного POST: дубль отметки невозможен на уровне БД
        indexes = [
            IndexModel([("schedule_id", 1), ("weekday", 1), ("slot", 1),
                        ("user_id", 1), ("date", 1)], unique=True),
        ]
