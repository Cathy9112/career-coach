"""Add persistent interview history and reports."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260805_0002"
down_revision: Union[str, None] = "20260803_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interview_histories",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=False),
        sa.Column("target_position", sa.String(length=200), nullable=False),
        sa.Column("difficulty", sa.String(length=50), nullable=False),
        sa.Column("answered_questions", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_interview_histories_user_id",
        "interview_histories",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_interview_histories_session_id",
        "interview_histories",
        ["session_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_interview_histories_session_id", table_name="interview_histories")
    op.drop_index("ix_interview_histories_user_id", table_name="interview_histories")
    op.drop_table("interview_histories")
