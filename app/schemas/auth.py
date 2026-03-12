from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from uuid import UUID
from datetime import datetime
from app.models.user import UserRole


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


# ── User ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    display_name: str
    password: str
    role: UserRole = UserRole.student

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("display_name")
    @classmethod
    def name_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Display name cannot be empty")
        return v.strip()


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: UserRole
    is_active: bool
    avatar_color: str
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    avatar_color: Optional[str] = None

    @field_validator("avatar_color")
    @classmethod
    def valid_hex(cls, v):
        if v and (not v.startswith("#") or len(v) != 7):
            raise ValueError("avatar_color must be a hex color like #4285F4")
        return v
