"""Adiciona o cliente dono da voz; nulo é voz do catálogo, visível a todos."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "voice",
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key("fk_voice_client_id", "voice", "client", ["client_id"], ["id"])
    op.create_index("ix_voice_client_id", "voice", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_voice_client_id", table_name="voice")
    op.drop_constraint("fk_voice_client_id", "voice", type_="foreignkey")
    op.drop_column("voice", "client_id")
