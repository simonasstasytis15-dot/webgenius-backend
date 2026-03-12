"""
ApiKeyService — handles the full lifecycle of student API keys.

Design rules:
  - The plaintext key enters this service and is immediately encrypted.
  - The plaintext key is held in memory only long enough to validate and encrypt it.
  - decrypt() is only called inside the proxy service, never in route handlers.
  - No route handler ever touches a plaintext key.
"""
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import HTTPException

from app.models.user import ApiKey, Provider, KeyStatus, User, UserRole
from app.core.encryption import key_encryption
from app.schemas.schemas import ApiKeySet, ApiKeyResponse


VALIDATION_ENDPOINTS = {
    Provider.gemini: {
        "url": "https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        "method": "GET",
    },
    Provider.elevenlabs: {
        "url": "https://api.elevenlabs.io/v1/user",
        "method": "GET",
        "headers": {"xi-api-key": "{key}"},
    },
    Provider.runway: {
        "url": "https://api.dev.runwayml.com/v1/organization",
        "method": "GET",
        "headers": {"Authorization": "Bearer {key}"},
    },
    Provider.openai: {
        "url": "https://api.openai.com/v1/models",
        "method": "GET",
        "headers": {"Authorization": "Bearer {key}"},
    },
}


class ApiKeyService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Validation ────────────────────────────────────────────────────────────

    async def validate_key_live(self, provider: Provider, plaintext_key: str) -> bool:
        """
        Make a lightweight call to the provider to confirm the key works.
        Returns True if valid, False if the key is rejected by the provider.
        Raises HTTPException for unexpected errors (network, etc).
        """
        config = VALIDATION_ENDPOINTS.get(provider)
        if not config:
            return True  # unknown provider — skip validation

        url = config["url"].format(key=plaintext_key)
        headers = {
            k: v.format(key=plaintext_key)
            for k, v in config.get("headers", {}).items()
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if config["method"] == "GET":
                    resp = await client.get(url, headers=headers)
                else:
                    resp = await client.post(url, headers=headers)

            # 200 = valid, 401/403 = bad key, anything else = treat as unknown
            if resp.status_code == 200:
                return True
            if resp.status_code in (401, 403):
                return False
            # 429 (rate limit) means the key exists and is valid
            if resp.status_code == 429:
                return True
            return False

        except httpx.TimeoutException:
            raise HTTPException(
                status_code=504,
                detail=f"Timeout validating {provider} key — try again"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Network error validating key: {str(e)}"
            )

    # ── Set key for a student ─────────────────────────────────────────────────

    async def set_key(
        self,
        student_id: str,
        payload: ApiKeySet,
        set_by: User,
    ) -> ApiKeyResponse:
        """
        Encrypt and store an API key for a student.
        Validates the key against the provider before saving.
        Only teachers/admins may call this.
        """
        # Permission check
        if set_by.role not in (UserRole.teacher, UserRole.admin):
            raise HTTPException(status_code=403, detail="Only teachers can set student API keys")

        # Confirm the student exists
        result = await self.db.execute(select(User).where(User.id == student_id))
        student = result.scalar_one_or_none()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")
        if student.role != UserRole.student:
            raise HTTPException(status_code=400, detail="Target user is not a student")

        # Validate key with provider
        is_valid = await self.validate_key_live(payload.provider, payload.api_key)
        if not is_valid:
            raise HTTPException(
                status_code=422,
                detail=f"The {payload.provider} API key was rejected by the provider. "
                       "Please double-check it and try again."
            )

        # Encrypt and mask
        encrypted = key_encryption.encrypt(payload.api_key)
        masked = key_encryption.mask(payload.api_key)
        label = payload.label or f"{student.display_name}'s {payload.provider} key"

        # Upsert — one key per student per provider
        result = await self.db.execute(
            select(ApiKey).where(
                ApiKey.user_id == student_id,
                ApiKey.provider == payload.provider,
            )
        )
        existing = result.scalar_one_or_none()

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        if existing:
            existing.key_encrypted = encrypted
            existing.key_masked = masked
            existing.key_label = label
            existing.status = KeyStatus.active
            existing.set_by_id = set_by.id
            existing.last_validated_at = now
            existing.updated_at = now
            api_key_row = existing
        else:
            api_key_row = ApiKey(
                user_id=student_id,
                provider=payload.provider,
                key_encrypted=encrypted,
                key_masked=masked,
                key_label=label,
                status=KeyStatus.active,
                set_by_id=set_by.id,
                last_validated_at=now,
            )
            self.db.add(api_key_row)

        await self.db.flush()
        return ApiKeyResponse.model_validate(api_key_row)

    # ── Bulk set for whole class ───────────────────────────────────────────────

    async def bulk_set_keys(
        self,
        student_key_map: dict[str, str],   # {student_id: plaintext_key}
        provider: Provider,
        set_by: User,
        label_prefix: str = "",
    ) -> dict[str, ApiKeyResponse | str]:
        """
        Set keys for multiple students in one call.
        Returns a result map: {student_id: ApiKeyResponse | error_string}
        Validates each key individually — one bad key doesn't block others.
        """
        results = {}
        for student_id, plaintext_key in student_key_map.items():
            try:
                payload = ApiKeySet(
                    provider=provider,
                    api_key=plaintext_key,
                    label=f"{label_prefix} {provider}".strip() if label_prefix else None,
                )
                resp = await self.set_key(student_id, payload, set_by)
                results[student_id] = resp
            except HTTPException as e:
                results[student_id] = f"Error: {e.detail}"
            except Exception as e:
                results[student_id] = f"Unexpected error: {str(e)}"
        return results

    # ── Revoke ────────────────────────────────────────────────────────────────

    async def revoke_key(
        self,
        student_id: str,
        provider: Provider,
        revoked_by: User,
    ) -> None:
        result = await self.db.execute(
            select(ApiKey).where(
                ApiKey.user_id == student_id,
                ApiKey.provider == provider,
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            raise HTTPException(status_code=404, detail="Key not found")

        if revoked_by.role not in (UserRole.teacher, UserRole.admin):
            raise HTTPException(status_code=403, detail="Only teachers can revoke keys")

        key.status = KeyStatus.revoked
        await self.db.flush()

    # ── Read (safe — no plaintext) ────────────────────────────────────────────

    async def get_student_keys(self, student_id: str) -> list[ApiKeyResponse]:
        """Return all keys for a student (masked, no plaintext)."""
        result = await self.db.execute(
            select(ApiKey).where(ApiKey.user_id == student_id)
        )
        keys = result.scalars().all()
        return [ApiKeyResponse.model_validate(k) for k in keys]

    async def get_class_key_status(self, student_ids: list[str]) -> dict[str, dict]:
        """
        For each student, return which providers are configured and their status.
        Used to populate the teacher dashboard setup checklist.
        """
        result = await self.db.execute(
            select(ApiKey).where(ApiKey.user_id.in_(student_ids))
        )
        all_keys = result.scalars().all()

        summary: dict[str, dict] = {sid: {} for sid in student_ids}
        for key in all_keys:
            summary[key.user_id][key.provider.value] = key.status.value
        return summary

    # ── Decrypt (server-side only, used by proxy) ─────────────────────────────

    async def get_decrypted_key(self, student_id: str, provider: Provider) -> str:
        """
        Retrieve and decrypt a student's API key.
        Only called from within the AI proxy service — never from route handlers.
        """
        result = await self.db.execute(
            select(ApiKey).where(
                ApiKey.user_id == student_id,
                ApiKey.provider == provider,
                ApiKey.status == KeyStatus.active,
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            raise HTTPException(
                status_code=402,
                detail=f"No active {provider} API key found for this student. "
                       "Ask your teacher to set it up."
            )
        return key_encryption.decrypt(key.key_encrypted)
