import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_teacher, get_current_user
from app.models.user import User, UserRole, Class, ClassMember
from app.schemas.schemas import ClassCreate, ClassResponse, ClassMemberResponse
from app.services.api_key_service import ApiKeyService
from app.core.redis import get_redis, UsageTracker

router = APIRouter(prefix="/classes", tags=["classes"])


@router.post("", response_model=ClassResponse, status_code=201)
async def create_class(
    payload: ClassCreate,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    invite_code = secrets.token_urlsafe(8)[:12].upper()
    class_ = Class(
        name=payload.name,
        description=payload.description,
        teacher_id=teacher.id,
        invite_code=invite_code,
    )
    db.add(class_)
    await db.flush()
    return {**class_.__dict__, "student_count": 0}


@router.get("/{class_id}", response_model=ClassResponse)
async def get_class(
    class_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Class).where(Class.id == class_id))
    class_ = result.scalar_one_or_none()
    if not class_:
        raise HTTPException(status_code=404, detail="Class not found")

    count_result = await db.execute(
        select(ClassMember).where(ClassMember.class_id == class_id)
    )
    student_count = len(count_result.scalars().all())
    return {**class_.__dict__, "student_count": student_count}


@router.post("/{class_id}/students/{student_id}", status_code=201)
async def add_student_to_class(
    class_id: str,
    student_id: str,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """Add an existing student account to a class."""
    # Verify class belongs to this teacher
    result = await db.execute(select(Class).where(Class.id == class_id))
    class_ = result.scalar_one_or_none()
    if not class_ or class_.teacher_id != teacher.id:
        raise HTTPException(status_code=404, detail="Class not found")

    # Verify student exists
    result = await db.execute(select(User).where(User.id == student_id))
    student = result.scalar_one_or_none()
    if not student or student.role != UserRole.student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Check not already a member
    result = await db.execute(
        select(ClassMember).where(
            ClassMember.class_id == class_id,
            ClassMember.user_id == student_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Student already in this class")

    member = ClassMember(class_id=class_id, user_id=student_id)
    db.add(member)
    await db.flush()
    return {"detail": "Student added to class"}


@router.get("/{class_id}/students", response_model=list[ClassMemberResponse])
async def list_class_students(
    class_id: str,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """
    Return all students in a class with their progress and API key status.
    This is the main data source for the teacher dashboard.
    """
    result = await db.execute(
        select(ClassMember).where(ClassMember.class_id == class_id)
    )
    memberships = result.scalars().all()
    student_ids = [m.user_id for m in memberships]

    if not student_ids:
        return []

    # Fetch all student users
    result = await db.execute(select(User).where(User.id.in_(student_ids)))
    users = {u.id: u for u in result.scalars().all()}

    # Fetch API key status for all students
    key_service = ApiKeyService(db)
    key_status = await key_service.get_class_key_status(student_ids)

    return [
        ClassMemberResponse(
            user_id=m.user_id,
            display_name=users[m.user_id].display_name,
            email=users[m.user_id].email,
            avatar_emoji=users[m.user_id].avatar_emoji,
            current_week=m.current_week,
            xp=m.xp,
            api_keys=key_status.get(m.user_id, {}),
            joined_at=m.joined_at,
        )
        for m in memberships
        if m.user_id in users
    ]


@router.get("/{class_id}/usage")
async def get_class_usage(
    class_id: str,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """Today's API usage summary for all students in the class."""
    result = await db.execute(
        select(ClassMember).where(ClassMember.class_id == class_id)
    )
    memberships = result.scalars().all()
    student_ids = [m.user_id for m in memberships]

    result = await db.execute(select(User).where(User.id.in_(student_ids)))
    users = {u.id: u for u in result.scalars().all()}

    redis = await get_redis()
    tracker = UsageTracker(redis)
    usage = await tracker.get_class_usage(student_ids)

    return [
        {
            "student_id": sid,
            "display_name": users[sid].display_name if sid in users else "Unknown",
            "today": usage.get(sid, {}),
        }
        for sid in student_ids
    ]
