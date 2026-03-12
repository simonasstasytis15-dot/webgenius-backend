import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey,
    Integer, Text, JSON, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin   = "admin"
    teacher = "teacher"
    student = "student"


class Provider(str, enum.Enum):
    gemini     = "gemini"       # covers text, imagen, tts, veo
    elevenlabs = "elevenlabs"
    runway     = "runway"
    openai     = "openai"       # future fallback


class KeyStatus(str, enum.Enum):
    active   = "active"
    invalid  = "invalid"    # failed live validation check
    revoked  = "revoked"    # manually revoked by teacher/admin


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False, default=UserRole.student)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    avatar_emoji: Mapped[str] = mapped_column(String(8), default="🧑", nullable=False)
    # Google Workspace account linked to this student (email from the business account)
    google_workspace_email: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    api_keys: Mapped[list["ApiKey"]] = relationship(
        "ApiKey", foreign_keys="ApiKey.user_id",
        back_populates="user", cascade="all, delete-orphan"
    )
    class_memberships: Mapped[list["ClassMember"]] = relationship(
        "ClassMember", back_populates="user", cascade="all, delete-orphan"
    )
    taught_classes: Mapped[list["Class"]] = relationship(
        "Class", back_populates="teacher"
    )
    usage_logs: Mapped[list["UsageLog"]] = relationship(
        "UsageLog", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User {self.email} [{self.role}]>"


# ── Class ─────────────────────────────────────────────────────────────────────

class Class(Base):
    __tablename__ = "classes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    teacher_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Relationships
    teacher: Mapped["User"] = relationship("User", back_populates="taught_classes")
    members: Mapped[list["ClassMember"]] = relationship(
        "ClassMember", back_populates="class_", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Class {self.name}>"


class ClassMember(Base):
    """Junction table: user ↔ class, tracking the student's progress."""
    __tablename__ = "class_members"
    __table_args__ = (UniqueConstraint("class_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    class_id: Mapped[str] = mapped_column(String(36), ForeignKey("classes.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    current_week: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Relationships
    class_: Mapped["Class"] = relationship("Class", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="class_memberships")


# ── API Keys ──────────────────────────────────────────────────────────────────

class ApiKey(Base):
    """
    One row per provider per student.

    key_encrypted  — Fernet-encrypted actual API key, never leaves the server
    key_masked     — Safe display string shown in the UI  e.g. "AIza••••••••xK9f"
    set_by_id      — The teacher/admin who attached this key to the student

    Only teachers/admins can write these rows.
    Students can read their own masked key and status, nothing more.
    """
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[Provider] = mapped_column(SAEnum(Provider), nullable=False)
    key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    key_label: Mapped[str] = mapped_column(String(100), nullable=True)    # "Maya's Gemini key"
    key_masked: Mapped[str] = mapped_column(String(20), nullable=False)   # "AIza••••••••xK9f"
    status: Mapped[KeyStatus] = mapped_column(
        SAEnum(KeyStatus), default=KeyStatus.active, nullable=False
    )
    # Who set this key (must be a teacher or admin)
    set_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    last_validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], back_populates="api_keys"
    )
    set_by: Mapped["User"] = relationship("User", foreign_keys=[set_by_id])

    def __repr__(self):
        return f"<ApiKey {self.provider} for user={self.user_id} [{self.status}]>"


# ── Usage Logs ────────────────────────────────────────────────────────────────

class UsageLog(Base):
    """
    Persistent audit trail — one row per proxied API call.
    Redis counters handle the fast rate-limit check path.
    This table feeds the teacher dashboard charts.
    """
    __tablename__ = "usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    # Granular service within provider: "imagen", "flash", "tts", "veo", "nano"
    service: Mapped[str] = mapped_column(String(50), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    # Flexible metadata: model used, token counts, error messages, etc.
    meta: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="usage_logs")
