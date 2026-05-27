import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import hash_password, require_teacher, get_current_user
from app.models.user import User, UserRole, Class, ClassMember
from app.schemas.schemas import UserCreate, UserUpdate, UserResponse, ClassMemberResponse
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/students", tags=["students"])


@router.post("", response_model=UserResponse, status_code=201)
async def create_student(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """
    Teacher creates a student account.
    Typically called once per student at the start of the course.
    """
    # Check email not already taken
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    student = User(
        email=payload.email,
        display_name=payload.display_name,
        hashed_password=hash_password(payload.password),
        role=UserRole.student,
        avatar_emoji=payload.avatar_emoji,
        google_workspace_email=payload.google_workspace_email,
    )
    db.add(student)
    await db.flush()
    return student


@router.post("/bulk", response_model=list[UserResponse], status_code=201)
async def create_students_bulk(
    payload: list[UserCreate],
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """
    Create multiple student accounts in one request.
    Useful for onboarding a full class at the start of term.
    """
    created = []
    for item in payload:
        result = await db.execute(select(User).where(User.email == item.email))
        if result.scalar_one_or_none():
            continue  # skip duplicates silently

        student = User(
            email=item.email,
            display_name=item.display_name,
            hashed_password=hash_password(item.password),
            role=UserRole.student,
            avatar_emoji=item.avatar_emoji,
            google_workspace_email=item.google_workspace_email,
        )
        db.add(student)
        created.append(student)

    await db.flush()
    return created


@router.get("/{student_id}", response_model=UserResponse)
async def get_student(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Teachers can view any student. Students can view only themselves."""
    if current_user.role == UserRole.student and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(select(User).where(User.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@router.patch("/{student_id}", response_model=UserResponse)
async def update_student(
    student_id: str,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    result = await db.execute(select(User).where(User.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(student, field, value)

    await db.flush()
    return student


@router.get("/{student_id}/progress")
async def get_student_progress(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return current week for a student (from their first class membership)."""
    if current_user.role == UserRole.student and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(
        select(ClassMember).where(ClassMember.user_id == student_id)
    )
    member = result.scalars().first()
    return {"current_week": member.current_week if member else 1}


@router.get("/{student_id}/keys")
async def get_student_key_status(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return which API providers are configured for this student.
    Safe — returns only masked keys and statuses, never plaintext.
    Students can view their own; teachers can view any in their class.
    """
    if current_user.role == UserRole.student and current_user.id != student_id:
        raise HTTPException(status_code=403, detail="Access denied")

    service = ApiKeyService(db)
    keys = await service.get_student_keys(student_id)
    return {k.provider.value: k for k in keys}
