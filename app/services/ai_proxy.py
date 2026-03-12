"""
AIProxyService — the only place in the codebase that makes calls to external AI APIs.

Flow for every call:
  1. Receive request from a route handler (student already authenticated)
  2. Fetch + decrypt the student's key via ApiKeyService
  3. Track usage in Redis (increment counter)
  4. Make the upstream call
  5. Log the result to UsageLog table
  6. Return the upstream response to the route handler

The student's API key is decrypted in-memory, used once, and never stored
in a variable that outlives this function call.
"""
import httpx
import time
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.user import Provider, UsageLog
from app.services.api_key_service import ApiKeyService
from app.core.redis import UsageTracker


# ── Gemini endpoint map ───────────────────────────────────────────────────────
# Using v1beta for Imagen and Veo, v1 for text/chat/tts

GEMINI_BASE = "https://generativelanguage.googleapis.com"

GEMINI_SERVICES = {
    "flash":    f"{GEMINI_BASE}/v1beta/models/gemini-2.0-flash:generateContent",
    "pro":      f"{GEMINI_BASE}/v1beta/models/gemini-1.5-pro:generateContent",
    "nano":     f"{GEMINI_BASE}/v1beta/models/gemini-nano:generateContent",
    "imagen3":  f"{GEMINI_BASE}/v1beta/models/imagen-3.0-generate-002:predict",
    "imagen3f": f"{GEMINI_BASE}/v1beta/models/imagen-3.0-fast-generate-001:predict",
    "tts":      f"{GEMINI_BASE}/v1beta/models/gemini-2.5-flash-preview-tts:generateContent",
    "veo2":     f"{GEMINI_BASE}/v1beta/models/veo-2.0-generate-001:predictLongRunning",
}

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


class AIProxyService:

    def __init__(self, db: AsyncSession, tracker: UsageTracker):
        self.db = db
        self.tracker = tracker
        self.key_service = ApiKeyService(db)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _log(
        self,
        user_id: str,
        provider: str,
        service: str,
        status_code: int,
        latency_ms: int,
        meta: dict = None,
    ):
        log = UsageLog(
            user_id=user_id,
            provider=provider,
            service=service,
            status_code=status_code,
            latency_ms=latency_ms,
            meta=meta or {},
        )
        self.db.add(log)
        # Don't await flush here — let the request lifecycle handle it

    async def _gemini_post(
        self,
        student_id: str,
        service_key: str,
        body: dict,
        redis_counter_key: str,
    ) -> dict:
        """Generic Gemini POST with key injection, timing, and logging."""
        api_key = await self.key_service.get_decrypted_key(student_id, Provider.gemini)
        url = GEMINI_SERVICES[service_key] + f"?key={api_key}"

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=body)
            latency = int((time.monotonic() - start) * 1000)

            await self.tracker.increment(student_id, redis_counter_key)
            await self._log(student_id, "gemini", service_key, resp.status_code, latency)

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Gemini API error: {resp.text[:300]}"
                )
            return resp.json()
        finally:
            # Key reference goes out of scope here — GC cleans it up
            del api_key

    # ── Gemini Text / Chat ────────────────────────────────────────────────────

    async def gemini_chat(
        self,
        student_id: str,
        messages: list[dict],
        model: str = "flash",
        system_prompt: str = None,
    ) -> dict:
        """
        Send a multi-turn conversation to Gemini.
        messages format: [{"role": "user"|"model", "parts": [{"text": "..."}]}]
        """
        body = {"contents": messages}
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        return await self._gemini_post(student_id, model, body, "gemini_text")

    # ── Gemini Imagen ─────────────────────────────────────────────────────────

    async def gemini_imagen(
        self,
        student_id: str,
        prompt: str,
        sample_count: int = 4,
        aspect_ratio: str = "1:1",
        model: str = "imagen3",
    ) -> dict:
        """
        Generate images with Imagen 3.
        Returns a dict with base64-encoded PNG images.
        """
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "sampleCount": min(sample_count, 4),
                "aspectRatio": aspect_ratio,
                "safetySetting": "block_most",
                "personGeneration": "dont_allow",  # appropriate for minors
            },
        }
        return await self._gemini_post(student_id, model, body, "gemini_imagen")

    # ── Gemini TTS ────────────────────────────────────────────────────────────

    async def gemini_tts(
        self,
        student_id: str,
        text: str,
        voice_name: str = "Aoede",
    ) -> dict:
        """
        Text-to-speech via Gemini 2.5 Flash TTS.
        Returns audio data in the response.
        """
        body = {
            "contents": [{"parts": [{"text": text}], "role": "user"}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice_name}
                    }
                },
            },
        }
        return await self._gemini_post(student_id, "tts", body, "gemini_tts")

    # ── Google Veo ────────────────────────────────────────────────────────────

    async def gemini_veo(
        self,
        student_id: str,
        prompt: str,
        duration_seconds: int = 5,
        aspect_ratio: str = "16:9",
    ) -> dict:
        """
        Video generation via Veo 2. Returns a long-running operation name
        that the client must poll until complete.
        """
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "durationSeconds": min(duration_seconds, 8),
                "aspectRatio": aspect_ratio,
                "personGeneration": "dont_allow",
            },
        }
        return await self._gemini_post(student_id, "veo2", body, "gemini_veo")

    async def gemini_veo_poll(self, student_id: str, operation_name: str) -> dict:
        """Poll a Veo long-running operation for completion."""
        api_key = await self.key_service.get_decrypted_key(student_id, Provider.gemini)
        url = f"{GEMINI_BASE}/v1beta/{operation_name}?key={api_key}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
            return resp.json()
        finally:
            del api_key

    # ── ElevenLabs TTS ────────────────────────────────────────────────────────

    async def elevenlabs_tts(
        self,
        student_id: str,
        text: str,
        voice_id: str,
        model_id: str = "eleven_turbo_v2_5",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> bytes:
        """
        Generate audio via ElevenLabs. Returns raw MP3 bytes.
        """
        api_key = await self.key_service.get_decrypted_key(student_id, Provider.elevenlabs)
        url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}"

        body = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
            },
        }
        headers = {
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=body, headers=headers)
            latency = int((time.monotonic() - start) * 1000)

            await self.tracker.increment(student_id, "elevenlabs")
            await self._log(
                student_id, "elevenlabs", "tts", resp.status_code, latency,
                {"voice_id": voice_id, "chars": len(text)}
            )

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"ElevenLabs error: {resp.text[:300]}"
                )
            return resp.content
        finally:
            del api_key
