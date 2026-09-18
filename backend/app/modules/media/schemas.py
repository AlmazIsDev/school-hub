from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class PostPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = Field(None, min_length=1, max_length=10000)
    assignee_id: str | None = None
    publish_at: datetime | None = None
    status: Literal["idea", "in_progress", "review", "published"] | None = None


class IdeaIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
