from pydantic import BaseModel, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.user import Provider as ApiProvider


# ── Class ─────────────────────────────────────────────────────────────────────

class ClassCreate(BaseModel):
    name: str
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Class name cannot be empty")
        return v.strip()


class ClassOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    join_code: str
    current_week: int
    is_active: bool
    created_at: datetime
    student_count: int = 0  # populated by service layer

    model_config = {"from_attributes": True}


class ClassUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    current_week: Optional[int] = None
    is_active: Optional[bool] = None


# ── Enrollment ────────────────────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    """Student joins a class via join code."""
    join_code: str


class EnrollmentOut(BaseModel):
    id: UUID
    student_id: UUID
    class_id: UUID
    enrolled_at: datetime
    is_active: bool
    # Current limits (None = class default applies)
    limit_gemini_text: Optional[int]
    limit_gemini_image: Optional[int]
    limit_elevenlabs: Optional[int]
    limit_runway: Optional[int]
    limit_openai: Optional[int]

    model_config = {"from_attributes": True}


class LimitsUpdate(BaseModel):
    """
    Teacher updates per-student rate limits.
    Set to null to revert to class default.
    """
    limit_gemini_text: Optional[int] = None
    limit_gemini_image: Optional[int] = None
    limit_elevenlabs: Optional[int] = None
    limit_runway: Optional[int] = None
    limit_openai: Optional[int] = None

    @field_validator("limit_gemini_text", "limit_gemini_image", "limit_elevenlabs",
                     "limit_runway", "limit_openai", mode="before")
    @classmethod
    def non_negative(cls, v):
        if v is not None and v < 0:
            raise ValueError("Limit must be 0 or greater")
        return v


# ── API Keys ──────────────────────────────────────────────────────────────────

class ApiKeyAssign(BaseModel):
    """Teacher assigns an API key to a student."""
    provider: ApiProvider
    api_key: str          # plaintext — encrypted immediately on receipt, never stored raw
    label: Optional[str] = None

    @field_validator("api_key")
    @classmethod
    def key_not_empty(cls, v):
        if not v.strip():
            raise ValueError("API key cannot be empty")
        return v.strip()


class ApiKeyOut(BaseModel):
    """
    Safe representation returned to the frontend.
    The real key is NEVER included — only the masked version.
    """
    id: UUID
    student_id: UUID
    provider: ApiProvider
    masked_key: str       # e.g. "AIza••••••••xK9f"
    label: Optional[str]
    is_active: bool
    assigned_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyRevoke(BaseModel):
    """Teacher revokes (soft-deletes) a key."""
    reason: Optional[str] = None


# ── Student summary for teacher dashboard ────────────────────────────────────

class StudentDashboardRow(BaseModel):
    student_id: UUID
    display_name: str
    email: str
    avatar_emoji: str
    enrolled_at: datetime
    is_active: bool

    # Key status per provider
    has_gemini_key: bool
    has_elevenlabs_key: bool
    has_runway_key: bool
    has_openai_key: bool

    # Today's usage
    usage_gemini_text_today: int
    usage_gemini_image_today: int
    usage_elevenlabs_today: int
    usage_runway_today: int

    # Effective limits
    limit_gemini_text: int
    limit_gemini_image: int
    limit_elevenlabs: int
    limit_runway: int

    model_config = {"from_attributes": True}
