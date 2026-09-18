from datetime import date as date_type

from pydantic import BaseModel, field_validator


class ZoneIn(BaseModel):
    name: str


class SlotIn(BaseModel):
    weekday: int
    slot: int
    user_id: str


class ScheduleIn(BaseModel):
    zone_id: str
    week_pattern: list[SlotIn]

    @field_validator("week_pattern")
    @classmethod
    def pattern_not_empty(cls, v):
        if not v:
            raise ValueError("week_pattern не может быть пустым")
        return v


class CompletionIn(BaseModel):
    schedule_id: str
    weekday: int
    slot: int
    date: str  # YYYY-MM-DD
    user_id: str | None = None  # только teacher/admin

    @field_validator("weekday")
    @classmethod
    def weekday_range(cls, v):
        if not 1 <= v <= 7:
            raise ValueError("weekday must be 1..7")
        return v

    @field_validator("slot")
    @classmethod
    def slot_range(cls, v):
        if not 1 <= v <= 8:
            raise ValueError("slot must be 1..8")
        return v

    @field_validator("date")
    @classmethod
    def date_format(cls, v):
        try:
            date_type.fromisoformat(v)
        except ValueError:
            raise ValueError("date must be YYYY-MM-DD")
        return v
