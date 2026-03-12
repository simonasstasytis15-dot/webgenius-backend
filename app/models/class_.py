import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Class(Base):
    """A teacher's class. Students are linked via Enrollment."""
    __tablename__ = "classes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    join_code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)  # e.g. "XK9F2B"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Current week (1–12) the class is on — teacher advances this
    current_week: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    teacher: Mapped["User"] = relationship("User", back_populates="taught_classes", foreign_keys=[teacher_id])
    enrollments: Mapped[list["Enrollment"]] = relationship("Enrollment", back_populates="class_", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Class '{self.name}' teacher={self.teacher_id}>"


class Enrollment(Base):
    """
    Links a student to a class.
    Also holds per-student rate limits (teacher configures, student cannot change).
    """
    __tablename__ = "enrollments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # ── Per-student daily rate limits (None = use class default) ──────────────
    # Teacher sets these per-student; proxy layer enforces them hard.
    limit_gemini_text: Mapped[int | None] = mapped_column(Integer, nullable=True)    # chat/text calls/day
    limit_gemini_image: Mapped[int | None] = mapped_column(Integer, nullable=True)   # Imagen calls/day
    limit_elevenlabs: Mapped[int | None] = mapped_column(Integer, nullable=True)     # TTS calls/day
    limit_runway: Mapped[int | None] = mapped_column(Integer, nullable=True)         # video calls/day
    limit_openai: Mapped[int | None] = mapped_column(Integer, nullable=True)         # OpenAI calls/day

    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    class_: Mapped["Class"] = relationship("Class", back_populates="enrollments")
    student: Mapped["User"] = relationship("User", back_populates="enrollments")

    def get_limit(self, provider: str, class_defaults: dict) -> int:
        """
        Returns the effective limit for a provider.
        Per-student override takes precedence; falls back to class default.
        """
        per_student = {
            "gemini_text":  self.limit_gemini_text,
            "gemini_image": self.limit_gemini_image,
            "elevenlabs":   self.limit_elevenlabs,
            "runway":       self.limit_runway,
            "openai":       self.limit_openai,
        }
        override = per_student.get(provider)
        return override if override is not None else class_defaults.get(provider, 0)
