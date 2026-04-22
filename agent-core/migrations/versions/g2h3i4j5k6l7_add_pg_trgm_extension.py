"""add_pg_trgm_extension

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-22 00:00:00.000000

"""
from alembic import op

revision = 'g2h3i4j5k6l7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade():
    pass
