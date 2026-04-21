"""Initial schema

Revision ID: 001
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("allowed_tools", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("allowed_mcp_servers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("max_turns", sa.Integer(), server_default=sa.text("20")),
        sa.Column("version", sa.Integer(), server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("spec_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_specs.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_service_of_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_input", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tool_output", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "ontology_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("parent_name", sa.String(), nullable=True),
        sa.Column("fields", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="provisional"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "edge_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("is_transitive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_inverse_of", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ontology_types.id"), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_by_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_in_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("src_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("dst_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("edge_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("edge_types.id"), nullable=False),
        sa.Column("created_by_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_in_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "ontology_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in ["ontology_events", "edges", "entities", "edge_types",
                  "ontology_types", "tool_calls", "messages", "runs", "agent_specs"]:
        op.drop_table(table)
