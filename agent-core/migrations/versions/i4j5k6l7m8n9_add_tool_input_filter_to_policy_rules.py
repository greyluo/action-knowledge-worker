"""add_tool_input_filter_to_policy_rules

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-04-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'i4j5k6l7m8n9'
down_revision = 'h3i4j5k6l7m8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policy_rules",
        sa.Column("tool_input_filter", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("policy_rules", "tool_input_filter")
