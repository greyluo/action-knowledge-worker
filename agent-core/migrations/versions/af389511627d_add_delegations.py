"""add_delegations

Revision ID: af389511627d
Revises: e1f2a3b4c5d6
Create Date: 2026-04-21 21:18:13.477364

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'af389511627d'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column(
        "parent_run_id", sa.UUID(as_uuid=True),
        sa.ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.create_table(
        "delegations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("parent_run_id", sa.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("child_run_id", sa.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_entity_id", sa.UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("to_agent_spec_id", sa.UUID(as_uuid=True), sa.ForeignKey("agent_specs.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("context_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("delegations")
    op.drop_column("runs", "parent_run_id")
