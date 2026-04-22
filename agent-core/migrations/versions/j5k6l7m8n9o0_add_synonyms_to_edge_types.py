"""add_synonyms_to_edge_types

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-04-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'j5k6l7m8n9o0'
down_revision = 'i4j5k6l7m8n9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "edge_types",
        sa.Column("synonyms", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("edge_types", "synonyms")
