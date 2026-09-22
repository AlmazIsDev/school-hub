from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from typing import Literal


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Quest(Document):
    school_id: str
    teacher_id: str
    class_id: str
    title: str
    structure: dict  # валидированный QuestStructure (см. quest_structure.py)
    status: Literal["draft", "published", "closed"] = "draft"
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "builder_quests"


class QuestRun(Document):
    school_id: str
    quest_id: str
    user_id: str
    finished: bool = False
    score: int = 0
    trace: list[dict] = Field(default_factory=list)  # [{block_id, value}]
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None

    class Settings:
        name = "builder_runs"
