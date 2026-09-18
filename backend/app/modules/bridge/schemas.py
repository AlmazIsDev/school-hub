from pydantic import BaseModel, field_validator


class ResolveIn(BaseModel):
    action: str  # dismiss | ban_days | ban_forever
    days: int | None = None

    @field_validator("days")
    @classmethod
    def days_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError("days must be > 0")
        return v


class StopWordIn(BaseModel):
    word: str
