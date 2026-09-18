from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class HelperTopic(Document):
    user_id: str
    topic: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_helper_topics"


class HelpRequest(Document):
    user_id: str
    topic: str
    status: Literal["waiting", "paired", "closed", "expired"] = "waiting"
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_help_requests"


class TutorPair(Document):
    request_id: str | None = None
    helper_id: str
    seeker_id: str
    chat_key: str
    status: Literal["active", "closed"] = "active"
    closed_at: datetime | None = None
    helper_score: int | None = None
    seeker_score: int | None = None
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_pairs"


class PairMessage(Document):
    pair_id: str
    sender_id: str
    text: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_pair_messages"


class Report(Document):
    reporter_id: str
    reported_user_id: str
    message_id: str | None = None
    reason: str
    status: Literal["open", "resolved"] = "open"
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_reports"


class Ban(Document):
    user_id: str
    until: datetime | None = None  # None = навсегда
    reason: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_bans"


class StopWord(Document):
    word: str
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "bridge_stop_words"
