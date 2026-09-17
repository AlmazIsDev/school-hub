from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ...core.db import Base

class SchoolClass(Base):
    __tablename__ = "school_classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    grade: Mapped[int]
    letter: Mapped[str] = mapped_column(String(2))
    users: Mapped[list["User"]] = relationship(back_populates="school_class")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # student|teacher|admin
    class_id: Mapped[int | None] = mapped_column(ForeignKey("school_classes.id"))
    vk_id: Mapped[int | None] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    school_class: Mapped["SchoolClass | None"] = relationship(back_populates="users")
