"""add_subject_source_to_policy_rules

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-04-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'h3i4j5k6l7m8'
down_revision = 'g2h3i4j5k6l7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policy_rules",
        sa.Column(
            "subject_source",
            sa.String(20),
            nullable=False,
            server_default="tool_input",
        ),
    )


def downgrade() -> None:
    op.drop_column("policy_rules", "subject_source")
