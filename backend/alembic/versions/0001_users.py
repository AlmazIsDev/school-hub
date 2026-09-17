"""users и school_classes

Revision ID: 0001
Revises:
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_classes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grade", sa.Integer(), nullable=False),
        sa.Column("letter", sa.String(length=2), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("school_classes.id"), nullable=True),
        sa.Column("vk_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_users_login", "users", ["login"])
    op.create_unique_constraint("uq_users_vk_id", "users", ["vk_id"])


def downgrade() -> None:
    op.drop_table("users")
    op.drop_table("school_classes")
