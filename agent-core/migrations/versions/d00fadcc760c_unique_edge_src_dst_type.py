"""unique_edge_src_dst_type

Revision ID: d00fadcc760c
Revises: c3d4e5f6a7b8
Create Date: 2026-04-21 15:51:05.884743

"""
from alembic import op
import sqlalchemy as sa


revision = 'd00fadcc760c'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_edge_src_dst_type", "edges", ["src_id", "dst_id", "edge_type_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_edge_src_dst_type", "edges", type_="unique")
