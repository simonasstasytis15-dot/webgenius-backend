import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import enum


class ApiProvider(str, enum.Enum):
    gemini     = "gemini"      # Google Gemini (text + Imagen + Veo)
    elevenlabs = "elevenlabs"  # ElevenLabs TTS
    runway     = "runway"      # Runway ML video
    openai     = "openai"      # OpenAI fallback


class StudentApiKey(Base):
    """
    One row per (student, provider). Teachers create/update these.
    The actual API key is stored AES-encrypted (Fernet).
    It is NEVER returned to the frontend — only decrypted server-side
    when the proxy layer makes an outbound API call.
    """
    __tablename__ = "student_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Who owns this key
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which teacher assigned it (audit trail)
    assigned_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    provider: Mapped[ApiProvider] = mapped_column(Enum(ApiProvider), nullable=False)

    # Encrypted key — use core.encryption.key_encryption to read/write
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)

    # A masked version stored for display (e.g. "AIza••••••••xK9f")
    # Recomputed every time the key is updated, never exposes the real key
    masked_key: Mapped[str] = mapped_column(String(40), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Optional label the teacher can set (e.g. "Maya's personal key")
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    student: Mapped["User"] = relationship(
        "User", back_populates="api_keys", foreign_keys=[student_id]
    )
    assigner: Mapped["User"] = relationship("User", foreign_keys=[assigned_by])

    def __repr__(self) -> str:
        return f"<StudentApiKey student={self.student_id} provider={self.provider} active={self.is_active}>"
