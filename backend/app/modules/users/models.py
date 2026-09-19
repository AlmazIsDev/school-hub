from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class SchoolClass(Document):
    grade: int
    letter: str

    class Settings:
        name = "school_classes"


class User(Document):
    login: str
    password_hash: str
    full_name: str
    role: str  # student|teacher|admin
    class_id: str | None = None
    vk_id: int | None = None
    password_temp: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
        # None-поля (vk_id, class_id) не пишем в документ: sparse-индекс vk_id
        # пропускает только отсутствующее поле, явный null индексируется и
        # второй пользователь с vk_id=None не может создаться
        keep_nulls = False
        indexes = [
            IndexModel([("login", 1)], unique=True),
            # sparse: у многих vk_id отсутствует, уникальность нужна только для привязанных
            IndexModel([("vk_id", 1)], unique=True, sparse=True),
        ]
