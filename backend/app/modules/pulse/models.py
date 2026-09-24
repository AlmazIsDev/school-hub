from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field


class EmbeddedQuestion(BaseModel):
    text: str
    type: str  # scale1_5|free_text


class Poll(Document):
    school_id: str
    teacher_id: str
    class_id: str
    title: str
    topic: str
    status: Literal["draft", "active", "closed"] = "draft"
    # Рассылка по poll.published дошла до бота (pub/sub не персистентен - флаг нужен для догонялки при рестарте бота)
    notified: bool = False
    questions: list[EmbeddedQuestion]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None

    class Settings:
        name = "pulse_polls"


class PollAnswer(Document):
    school_id: str
    poll_id: str
    question_idx: int  # индекс в Poll.questions, не ObjectId - вопросы вложены
    value: str  # шкала - "1".."5", свободный - текст
    # Без user_id - анонимность сознательная. Дедупликация через Redis
    # (SET NX с TTL); после рестарта Redis возможен повторный ответ - accepted trade-off.
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "pulse_answers"
