from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_teacher
from app.models.user import User, Provider
from app.schemas.schemas import ApiKeySet, ApiKeyBulkSet, ApiKeyResponse
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.put("/student/{student_id}", response_model=ApiKeyResponse)
async def set_student_api_key(
    student_id: str,
    payload: ApiKeySet,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """
    Set (or replace) an API key for a single student.

    The plaintext key is validated against the provider, then immediately
    encrypted and stored. The plaintext is never logged or returned.

    Responds with the safe masked representation.
    """
    service = ApiKeyService(db)
    return await service.set_key(student_id, payload, teacher)


@router.post("/bulk", response_model=dict)
async def bulk_set_api_keys(
    payload: ApiKeyBulkSet,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """
    Set API keys for multiple students in one request.

    Payload:
    {
      "provider": "gemini",
      "student_ids": ["uuid1", "uuid2", ...],
      "api_keys": {
        "uuid1": "AIzaSy...",
        "uuid2": "AIzaSy..."
      },
      "label_prefix": "Spring 2025"
    }

    Returns a result per student: ApiKeyResponse on success, error string on failure.
    One bad key does not block the others.
    """
    # Validate that api_keys covers all student_ids
    missing = set(payload.student_ids) - set(payload.api_keys.keys())
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing keys for student IDs: {list(missing)}"
        )

    service = ApiKeyService(db)
    results = await service.bulk_set_keys(
        student_key_map={sid: payload.api_keys[sid] for sid in payload.student_ids},
        provider=payload.provider,
        set_by=teacher,
        label_prefix=payload.label_prefix or "",
    )

    # Serialize: ApiKeyResponse → dict, errors stay as strings
    serialized = {}
    for student_id, result in results.items():
        if isinstance(result, ApiKeyResponse):
            serialized[student_id] = {"status": "ok", "key": result.model_dump()}
        else:
            serialized[student_id] = {"status": "error", "detail": result}

    return serialized


@router.delete("/student/{student_id}/{provider}")
async def revoke_student_api_key(
    student_id: str,
    provider: Provider,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """Revoke a student's API key for a given provider."""
    service = ApiKeyService(db)
    await service.revoke_key(student_id, provider, teacher)
    return {"detail": f"{provider} key revoked for student {student_id}"}


@router.post("/student/{student_id}/{provider}/validate")
async def revalidate_key(
    student_id: str,
    provider: Provider,
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_teacher),
):
    """
    Re-run a live validation check on a student's stored key.
    Useful if a key was previously flagged as invalid but has since been fixed.
    """
    from sqlalchemy import select
    from app.models.user import ApiKey, KeyStatus
    from datetime import datetime, timezone

    service = ApiKeyService(db)
    plaintext = await service.get_decrypted_key(student_id, provider)
    is_valid = await service.validate_key_live(provider, plaintext)
    del plaintext  # don't hold it longer than needed

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == student_id,
            ApiKey.provider == provider,
        )
    )
    key = result.scalar_one_or_none()
    if key:
        key.status = KeyStatus.active if is_valid else KeyStatus.invalid
        key.last_validated_at = datetime.now(timezone.utc)

    return {
        "valid": is_valid,
        "status": key.status.value if key else "not_found"
    }
