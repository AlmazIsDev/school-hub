from typing import Literal

from pydantic import BaseModel, field_validator


class ResolveIn(BaseModel):
    action: Literal["dismiss", "ban_days", "ban_forever"]
    days: int | None = None

    @field_validator("days")
    @classmethod
    def days_positive(cls, v):
        if v is not None and not (0 < v <= 3650):
            raise ValueError("days must be in 1..3650")
        return v


class StopWordIn(BaseModel):
    word: str
