"""remove next_in_chain edge type

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-21 12:00:00.000000

"""
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM edges
        WHERE edge_type_id = (
            SELECT id FROM edge_types WHERE name = 'next_in_chain'
        )
    """)
    op.execute("DELETE FROM edge_types WHERE name = 'next_in_chain'")


def downgrade() -> None:
    op.execute("""
        INSERT INTO edge_types (name, is_transitive, is_inverse_of)
        VALUES ('next_in_chain', false, NULL)
        ON CONFLICT (name) DO NOTHING
    """)
