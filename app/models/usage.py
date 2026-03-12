import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, Float, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from app.models.api_key import ApiProvider
import enum


class UsageStatus(str, enum.Enum):
    success      = "success"
    rate_limited = "rate_limited"   # blocked by our hard limit before hitting provider
    provider_error = "provider_error"  # provider returned an error


class ApiUsage(Base):
    """
    One row per proxied API call. Used to:
      - enforce hard daily limits (checked against Redis, persisted here)
      - power the teacher dashboard usage view
      - give teachers visibility into which students are hitting limits
    """
    __tablename__ = "api_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id"), nullable=True, index=True
    )

    provider: Mapped[ApiProvider] = mapped_column(Enum(ApiProvider), nullable=False, index=True)

    # Sub-categorise calls within a provider (e.g. "imagen", "gemini-flash", "tts")
    endpoint: Mapped[str] = mapped_column(String(60), nullable=False)

    status: Mapped[UsageStatus] = mapped_column(
        Enum(UsageStatus), nullable=False, default=UsageStatus.success
    )

    # How many "units" this call consumed (usually 1, but Imagen grid = 4)
    units: Mapped[int] = mapped_column(Integer, default=1)

    # Provider-reported token/cost info where available
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Error message if status != success
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # Relationships
    student: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return f"<ApiUsage {self.provider}/{self.endpoint} student={self.student_id} {self.status}>"
