"""
Teacher dashboard routes.

Gives teachers a real-time view of their class:
  - Which students have which API keys configured
  - Today's usage per student per provider
  - Per-student rate limit overrides
  - Ability to reset a student's daily counter
"""
from uuid import UUID
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from app.core.database import get_db
from app.core.security import require_teacher
from app.models.user import User
from app.models.class_ import Class, Enrollment
from app.models.api_key import StudentApiKey, ApiProvider
from app.models.usage import ApiUsage, UsageStatus
from app.services.rate_limiter import rate_limiter
from app.schemas.classroom import StudentDashboardRow, LimitsUpdate, EnrollmentOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Default limits mirrored here for display (source of truth is ai_proxy.py DEFAULT_LIMITS)
_DEFAULTS = {
    "gemini_text": 100,
    "gemini_image": 20,
    "elevenlabs": 15,
    "runway": 5,
    "openai": 50,
}


@router.get("/class/{class_id}", response_model=list[StudentDashboardRow])
async def class_dashboard(
    class_id: UUID,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Full dashboard for a class — one row per student with:
    - Key status per provider
    - Today's usage from Redis (fast)
    - Effective rate limits
    """
    # Verify ownership
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    # Get all active enrollments with student info
    enroll_result = await db.execute(
        select(Enrollment, User).join(User, Enrollment.student_id == User.id).where(
            Enrollment.class_id == class_id,
            Enrollment.is_active == True,
        )
    )
    rows = enroll_result.all()

    # Get all API keys for students in this class in one query
    student_ids = [r.User.id for r in rows]
    key_result = await db.execute(
        select(StudentApiKey).where(
            StudentApiKey.student_id.in_(student_ids),
            StudentApiKey.is_active == True,
        )
    )
    all_keys = key_result.scalars().all()

    # Build key status map: {student_id: set of providers}
    key_map: dict[UUID, set] = {sid: set() for sid in student_ids}
    for key in all_keys:
        key_map[key.student_id].add(key.provider)

    dashboard_rows = []
    for enrollment, student in rows:
        # Get today's usage from Redis (fast path)
        usage = await rate_limiter.get_all_usage_today(str(student.id))

        # Effective limits (per-student override or default)
        eff_limits = {
            "gemini_text":  enrollment.limit_gemini_text  or _DEFAULTS["gemini_text"],
            "gemini_image": enrollment.limit_gemini_image or _DEFAULTS["gemini_image"],
            "elevenlabs":   enrollment.limit_elevenlabs   or _DEFAULTS["elevenlabs"],
            "runway":       enrollment.limit_runway        or _DEFAULTS["runway"],
        }

        providers = key_map.get(student.id, set())
        dashboard_rows.append(StudentDashboardRow(
            student_id=student.id,
            display_name=student.display_name,
            email=student.email,
            avatar_color=student.avatar_color,
            enrolled_at=enrollment.enrolled_at,
            is_active=enrollment.is_active,
            has_gemini_key=ApiProvider.gemini in providers,
            has_elevenlabs_key=ApiProvider.elevenlabs in providers,
            has_runway_key=ApiProvider.runway in providers,
            has_openai_key=ApiProvider.openai in providers,
            usage_gemini_text_today=usage.get("gemini_text", 0),
            usage_gemini_image_today=usage.get("gemini_image", 0),
            usage_elevenlabs_today=usage.get("elevenlabs", 0),
            usage_runway_today=usage.get("runway", 0),
            limit_gemini_text=eff_limits["gemini_text"],
            limit_gemini_image=eff_limits["gemini_image"],
            limit_elevenlabs=eff_limits["elevenlabs"],
            limit_runway=eff_limits["runway"],
        ))

    return dashboard_rows


@router.post("/class/{class_id}/students/{student_id}/reset-usage")
async def reset_student_usage(
    class_id: UUID,
    student_id: UUID,
    provider: ApiProvider | None = None,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Reset a student's daily usage counter — all providers or just one.
    Use when a student accidentally burned through their limit.
    """
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    await rate_limiter.reset_student(
        str(student_id),
        provider.value if provider else None,
    )
    return {
        "detail": f"Usage reset for student {student_id}"
                  + (f" ({provider.value} only)" if provider else " (all providers)"),
        "reset_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/class/{class_id}/usage-history")
async def class_usage_history(
    class_id: UUID,
    days: int = 7,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """
    Historical usage for a class from the database.
    Returns daily totals per provider for the last N days.
    Useful for seeing trends — e.g. which day had a spike.
    """
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    result = await db.execute(
        select(
            func.date(ApiUsage.called_at).label("day"),
            ApiUsage.provider,
            func.sum(ApiUsage.units).label("total_units"),
            func.count().label("call_count"),
        )
        .where(
            ApiUsage.class_id == class_id,
            ApiUsage.status == UsageStatus.success,
        )
        .group_by(func.date(ApiUsage.called_at), ApiUsage.provider)
        .order_by(func.date(ApiUsage.called_at).desc())
        .limit(days * 4)  # 4 providers × days
    )

    return [
        {
            "day": str(row.day),
            "provider": row.provider,
            "total_units": row.total_units,
            "call_count": row.call_count,
        }
        for row in result.all()
    ]


@router.get("/class/{class_id}/students/{student_id}/keys")
async def get_student_keys(
    class_id: UUID,
    student_id: UUID,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Get all API keys assigned to a student (masked, never plaintext)."""
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    result = await db.execute(
        select(StudentApiKey).where(
            StudentApiKey.student_id == student_id,
        ).order_by(StudentApiKey.provider)
    )
    keys = result.scalars().all()

    return [
        {
            "id": str(k.id),
            "provider": k.provider.value,
            "masked_key": k.masked_key,
            "label": k.label,
            "is_active": k.is_active,
            "created_at": k.created_at.isoformat(),
            "updated_at": k.updated_at.isoformat(),
        }
        for k in keys
    ]
