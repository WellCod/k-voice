"""Adiciona ref_text à tabela voice para suporte a clonagem de voz."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("voice", sa.Column("ref_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("voice", "ref_text")
