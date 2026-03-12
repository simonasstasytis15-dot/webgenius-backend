import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Enum, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import enum


class ProjectType(str, enum.Enum):
    image_gallery = "image_gallery"   # Stage 1 — Imagen outputs
    illustrated_story = "illustrated_story"  # Stage 1 — story + images
    voiceover = "voiceover"           # Stage 2 — TTS audio
    animated_clip = "animated_clip"   # Stage 2 — Veo/Runway video
    short_film = "short_film"         # Stage 2 — assembled film
    python_script = "python_script"   # Stage 3 — chatbot code
    webpage = "webpage"               # Stage 3 — HTML/CSS
    mini_game = "mini_game"           # Stage 3 — Pygame
    portfolio = "portfolio"           # Stage 3 — final portfolio


class Project(Base):
    """
    Stores a student's work-in-progress and submitted deliverables.
    `content` is a flexible JSON blob — schema varies by project_type.
    """
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("classes.id"), nullable=False, index=True
    )

    project_type: Mapped[ProjectType] = mapped_column(Enum(ProjectType), nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="Untitled")

    # Flexible content store — each project type defines its own JSON schema
    # e.g. image_gallery: {"images": [{"prompt": "...", "url": "...", "selected": true}]}
    # e.g. python_script:  {"code": "...", "last_run_output": "...", "language": "python"}
    content: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Teacher feedback
    teacher_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "A", "85%", etc.

    # Workflow state
    is_submitted: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    student: Mapped["User"] = relationship("User", back_populates="projects")
