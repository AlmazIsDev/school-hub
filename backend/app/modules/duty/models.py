from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddedSlot(BaseModel):
    weekday: int  # 1..7, пн..вс
    slot: int  # 1..8
    user_id: str


class DutyZone(Document):
    name: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "duty_zones"


class DutySchedule(Document):
    teacher_id: str
    zone_id: str
    week_pattern: list[EmbeddedSlot]
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "duty_schedules"


class DutyCompletion(Document):
    schedule_id: str
    weekday: int
    slot: int
    user_id: str
    date: datetime  # только дата, UTC, полночь
    marked_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "duty_completions"
