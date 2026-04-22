"""add_session_id_to_runs

Revision ID: f1a2b3c4d5e6
Revises: af389511627d
Create Date: 2026-04-21 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'af389511627d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("session_id", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "session_id")
