"""Adiciona a voz equivalente na ElevenLabs para o fallback."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("voice", sa.Column("elevenlabs_voice_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("voice", "elevenlabs_voice_id")
