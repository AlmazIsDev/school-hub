from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Post(Document):
    title: str
    body: str
    status: Literal["idea", "in_progress", "review", "published"] = "idea"
    assignee_id: str | None = None
    publish_at: datetime | None = None
    # момент фактического перехода в published — фильтр догонялки бота
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "media_posts"


class PostIdea(Document):
    author_id: str
    text: str
    status: Literal["new", "accepted", "rejected"] = "new"
    created_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "media_ideas"
