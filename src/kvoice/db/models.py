from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


class VoiceOrigin(enum.StrEnum):
    preset = "preset"
    clone = "clone"
    finetune = "finetune"


class RoutingMode(enum.StrEnum):
    kvoice = "kvoice"
    elevenlabs = "elevenlabs"
    percentual = "percentual"


class BatchStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Client(Base):
    __tablename__ = "client"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tokens: Mapped[list[ApiToken]] = relationship(back_populates="client", lazy="raise")
    pronunciation_entries: Mapped[list[PronunciationEntry]] = relationship(
        back_populates="client", lazy="raise"
    )
    routing_rules: Mapped[list[RoutingRule]] = relationship(back_populates="client", lazy="raise")
    usage_events: Mapped[list[UsageEvent]] = relationship(back_populates="client", lazy="raise")
    batch_jobs: Mapped[list[BatchJob]] = relationship(back_populates="client", lazy="raise")


class ApiToken(Base):
    __tablename__ = "api_token"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    client: Mapped[Client] = relationship(back_populates="tokens", lazy="raise")

    def has_scope(self, scope: str) -> bool:
        return "admin" in self.scopes_list or scope in self.scopes_list

    @property
    def scopes_list(self) -> list[str]:
        return [s for s in self.scopes.split(",") if s]


class Voice(Base):
    __tablename__ = "voice"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    age_range: Mapped[str | None] = mapped_column(String(32), nullable=True)
    style: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="pt-BR")
    origin: Mapped[VoiceOrigin] = mapped_column(
        Enum(VoiceOrigin, name="voice_origin"), nullable=False
    )
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ref_audio_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    consents: Mapped[list[VoiceConsent]] = relationship(back_populates="voice", lazy="raise")


class VoiceConsent(Base):
    __tablename__ = "voice_consent"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    voice_id: Mapped[str] = mapped_column(String(128), ForeignKey("voice.id"), nullable=False)
    consenter_name: Mapped[str] = mapped_column(String(255), nullable=False)
    consenter_email: Mapped[str] = mapped_column(String(255), nullable=False)
    audio_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    voice: Mapped[Voice] = relationship(back_populates="consents", lazy="raise")


class PronunciationEntry(Base):
    __tablename__ = "pronunciation_entry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id"), nullable=True
    )
    term: Mapped[str] = mapped_column(String(255), nullable=False)
    expansion: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    client: Mapped[Client | None] = relationship(
        back_populates="pronunciation_entries", lazy="raise"
    )


class RoutingRule(Base):
    __tablename__ = "routing_rule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id"), nullable=False
    )
    mode: Mapped[RoutingMode] = mapped_column(
        Enum(RoutingMode, name="routing_mode"), nullable=False, default=RoutingMode.kvoice
    )
    kvoice_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    voice_mapping: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    client: Mapped[Client] = relationship(back_populates="routing_rules", lazy="raise")


class UsageEvent(Base):
    __tablename__ = "usage_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id"), nullable=False
    )
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    characters: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_ms: Mapped[float] = mapped_column(Float, nullable=False)
    ttfa_ms: Mapped[float] = mapped_column(Float, nullable=False)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False)
    engine: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    client: Mapped[Client] = relationship(back_populates="usage_events", lazy="raise")


class BatchJob(Base):
    __tablename__ = "batch_job"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id"), nullable=False
    )
    voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="batch_status"), nullable=False, default=BatchStatus.pending
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False, default="ogg_opus")
    output_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client: Mapped[Client] = relationship(back_populates="batch_jobs", lazy="raise")
