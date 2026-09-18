from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field


class EmbeddedQuestion(BaseModel):
    text: str
    type: str  # scale1_5|free_text


class Poll(Document):
    teacher_id: str
    class_id: str
    title: str
    topic: str
    status: str = "draft"  # draft|active|closed
    questions: list[EmbeddedQuestion]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None

    class Settings:
        name = "pulse_polls"


class PollAnswer(Document):
    poll_id: str
    question_idx: int  # индекс в Poll.questions, не ObjectId — вопросы вложены
    value: str  # шкала — "1".."5", свободный — текст
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "pulse_answers"
