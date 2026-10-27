"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_DT = sa.DateTime(timezone=True)
_UUID = postgresql.UUID(as_uuid=True)


def _created_at() -> sa.Column[sa.DateTime]:  # type: ignore[type-arg]
    return sa.Column("created_at", _DT, server_default=sa.func.now(), nullable=False)


def _client_fk(nullable: bool = False) -> sa.Column[postgresql.UUID]:  # type: ignore[type-arg]
    return sa.Column("client_id", _UUID, sa.ForeignKey("client.id"), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "client",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        _created_at(),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "api_token",
        sa.Column("id", _UUID, primary_key=True),
        _client_fk(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.Text, nullable=False, server_default=""),
        _created_at(),
        sa.Column("last_used_at", _DT, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )
    op.create_index("ix_api_token_client_id", "api_token", ["client_id"])

    op.create_table(
        "voice",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("gender", sa.String(32), nullable=True),
        sa.Column("age_range", sa.String(32), nullable=True),
        sa.Column("style", sa.String(64), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="pt-BR"),
        sa.Column(
            "origin",
            sa.Enum("preset", "clone", "finetune", name="voice_origin"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(255), nullable=True),
        sa.Column("ref_audio_key", sa.String(512), nullable=True),
        sa.Column("style_prompt", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        _created_at(),
    )

    op.create_table(
        "voice_consent",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("voice_id", sa.String(128), sa.ForeignKey("voice.id"), nullable=False),
        sa.Column("consenter_name", sa.String(255), nullable=False),
        sa.Column("consenter_email", sa.String(255), nullable=False),
        sa.Column("audio_key", sa.String(512), nullable=False),
        _created_at(),
    )

    op.create_table(
        "pronunciation_entry",
        sa.Column("id", _UUID, primary_key=True),
        _client_fk(nullable=True),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("expansion", sa.String(1024), nullable=False),
        sa.Column("is_regex", sa.Boolean, nullable=False, server_default="false"),
    )

    op.create_table(
        "routing_rule",
        sa.Column("id", _UUID, primary_key=True),
        _client_fk(),
        sa.Column(
            "mode",
            sa.Enum("kvoice", "elevenlabs", "percentual", name="routing_mode"),
            nullable=False,
            server_default="kvoice",
        ),
        sa.Column("kvoice_pct", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("voice_mapping", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
    )

    op.create_table(
        "usage_event",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("request_id", _UUID, nullable=False),
        _client_fk(),
        sa.Column("voice_id", sa.String(128), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("characters", sa.Integer, nullable=False),
        sa.Column("audio_ms", sa.Float, nullable=False),
        sa.Column("ttfa_ms", sa.Float, nullable=False),
        sa.Column("total_ms", sa.Float, nullable=False),
        sa.Column("engine", sa.String(32), nullable=False),
        sa.Column("fallback", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("fallback_reason", sa.String(64), nullable=True),
        _created_at(),
    )
    op.create_index("ix_usage_event_request_id", "usage_event", ["request_id"])
    op.create_index("ix_usage_event_created_at", "usage_event", ["created_at"])
    op.create_index("ix_usage_event_client_id", "usage_event", ["client_id"])

    op.create_table(
        "batch_job",
        sa.Column("id", _UUID, primary_key=True),
        _client_fk(),
        sa.Column("voice_id", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "processing", "done", "failed", name="batch_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("input_text", sa.Text, nullable=False),
        sa.Column("format", sa.String(32), nullable=False, server_default="ogg_opus"),
        sa.Column("output_key", sa.String(512), nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        _created_at(),
        sa.Column("completed_at", _DT, nullable=True),
        sa.Column("expires_at", _DT, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("batch_job")
    op.drop_table("usage_event")
    op.drop_table("routing_rule")
    op.drop_table("pronunciation_entry")
    op.drop_table("voice_consent")
    op.drop_table("voice")
    op.drop_table("api_token")
    op.drop_table("client")
    op.execute("DROP TYPE IF EXISTS voice_origin")
    op.execute("DROP TYPE IF EXISTS routing_mode")
    op.execute("DROP TYPE IF EXISTS batch_status")
