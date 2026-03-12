from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
from app.models.user import UserRole, Provider, KeyStatus


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: UserRole
    display_name: str


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    """Used by teacher/admin to create a student account."""
    email: EmailStr
    display_name: str
    password: str
    role: UserRole = UserRole.student
    avatar_emoji: str = "🧑"
    google_workspace_email: Optional[EmailStr] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar_emoji: Optional[str] = None
    google_workspace_email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    avatar_emoji: str
    google_workspace_email: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Classes ───────────────────────────────────────────────────────────────────

class ClassCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ClassResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    invite_code: str
    is_active: bool
    teacher_id: str
    created_at: datetime
    student_count: int = 0

    class Config:
        from_attributes = True


class ClassMemberResponse(BaseModel):
    user_id: str
    display_name: str
    email: str
    avatar_emoji: str
    current_week: int
    xp: int
    # API key status per provider — safe to show, no actual keys
    api_keys: dict[str, str] = {}   # {"gemini": "active", "elevenlabs": "missing"}
    joined_at: datetime

    class Config:
        from_attributes = True


# ── API Keys ──────────────────────────────────────────────────────────────────

class ApiKeySet(BaseModel):
    """
    Payload a teacher sends to attach an API key to a student.
    The actual key is write-only — it is encrypted on arrival and
    never returned in any response.
    """
    provider: Provider
    api_key: str               # the real key — encrypted immediately on receipt
    label: Optional[str] = None

    @field_validator("api_key")
    @classmethod
    def key_not_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("API key cannot be empty")
        return v


class ApiKeyBulkSet(BaseModel):
    """Set the same key for multiple students at once — useful when a teacher
    has one Google Workspace project with per-user API keys."""
    student_ids: list[str]
    provider: Provider
    api_keys: dict[str, str]   # {student_id: "actual_key"}
    label_prefix: Optional[str] = None


class ApiKeyResponse(BaseModel):
    """Safe representation — never includes the real key."""
    id: str
    provider: Provider
    key_masked: str
    key_label: Optional[str]
    status: KeyStatus
    set_by_id: str
    last_validated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApiKeyStatusResponse(BaseModel):
    """Per-student summary of which providers are configured."""
    student_id: str
    providers: dict[str, ApiKeyResponse]   # keyed by provider name


# ── Usage ─────────────────────────────────────────────────────────────────────

class UsageSummary(BaseModel):
    student_id: str
    display_name: str
    today: dict[str, int]      # {"gemini_text": 12, "gemini_imagen": 4, ...}
    is_active: bool            # seen in last 15 min (Redis presence key)


class ClassUsageSummary(BaseModel):
    class_id: str
    class_name: str
    generated_at: datetime
    students: list[UsageSummary]
