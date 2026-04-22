"""add domain and range_ to edge_types

Revision ID: c3d4e5f6a7b8
Revises: b2b7c96e4b5b
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2b7c96e4b5b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("edge_types", sa.Column("domain", sa.String(), nullable=True))
    op.add_column("edge_types", sa.Column("range_", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("edge_types", "range_")
    op.drop_column("edge_types", "domain")
