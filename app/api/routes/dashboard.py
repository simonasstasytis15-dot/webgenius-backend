"""
Teacher dashboard routes — class overview, usage stats, key status.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import require_teacher
from app.models.user import User, Class, ClassMember, ApiKey, Provider, UsageLog
from app.services.rate_limiter import rate_limiter
from app.core.redis import get_redis, UsageTracker

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/class/{class_id}")
async def class_dashboard(
    class_id: str,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Full dashboard for a class — one row per student with key status and today's usage."""
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    # Get all members
    members_result = await db.execute(
        select(ClassMember, User)
        .join(User, ClassMember.user_id == User.id)
        .where(ClassMember.class_id == class_id)
    )
    rows = members_result.all()
    student_ids = [r.User.id for r in rows]

    # Get API keys for all students
    keys_result = await db.execute(
        select(ApiKey).where(ApiKey.user_id.in_(student_ids))
    )
    all_keys = keys_result.scalars().all()
    key_map: dict[str, dict] = {sid: {} for sid in student_ids}
    for key in all_keys:
        key_map[key.user_id][key.provider.value] = key.status.value

    redis = await get_redis()
    tracker = UsageTracker(redis)

    dashboard_rows = []
    for member, student in rows:
        usage = await tracker.get_all_today(str(student.id))
        dashboard_rows.append({
            "student_id": student.id,
            "display_name": student.display_name,
            "email": student.email,
            "avatar_emoji": student.avatar_emoji,
            "current_week": member.current_week,
            "xp": member.xp,
            "api_keys": key_map.get(student.id, {}),
            "usage_today": usage,
            "joined_at": member.joined_at.isoformat(),
        })

    return dashboard_rows


@router.post("/class/{class_id}/students/{student_id}/reset-usage")
async def reset_student_usage(
    class_id: str,
    student_id: str,
    provider: str = None,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Reset a student's daily usage counter."""
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    await rate_limiter.reset_student(student_id, provider)
    return {
        "detail": f"Usage reset for student {student_id}",
        "reset_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/class/{class_id}/usage-history")
async def class_usage_history(
    class_id: str,
    days: int = 7,
    teacher: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    """Historical usage for a class from the database."""
    class_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher.id)
    )
    if not class_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Class not found")

    # Get member ids for this class
    members_result = await db.execute(
        select(ClassMember.user_id).where(ClassMember.class_id == class_id)
    )
    student_ids = [r[0] for r in members_result.all()]

    result = await db.execute(
        select(
            func.date(UsageLog.created_at).label("day"),
            UsageLog.provider,
            func.count().label("call_count"),
        )
        .where(UsageLog.user_id.in_(student_ids))
        .group_by(func.date(UsageLog.created_at), UsageLog.provider)
        .order_by(func.date(UsageLog.created_at).desc())
        .limit(days * 5)
    )

    return [
        {"day": str(row.day), "provider": row.provider, "call_count": row.call_count}
        for row in result.all()
    ]
