from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.redis import get_redis, UsageTracker
from app.models.user import User
from app.services.ai_proxy import AIProxyService

router = APIRouter(prefix="/ai", tags=["ai"])


def get_proxy(db: AsyncSession = Depends(get_db)):
    """Dependency that wires up the proxy service — injected into each route."""
    async def _inner(redis=Depends(get_redis)):
        tracker = UsageTracker(redis)
        return AIProxyService(db, tracker)
    return _inner


# ── Request / response schemas ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str          # "user" or "model"
    text: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str = "flash"
    system_prompt: Optional[str] = None


class ImagenRequest(BaseModel):
    prompt: str
    sample_count: int = 4
    aspect_ratio: str = "1:1"
    model: str = "imagen3"


class TTSRequest(BaseModel):
    text: str
    voice_name: str = "Aoede"    # Gemini built-in voice


class ElevenLabsRequest(BaseModel):
    text: str
    voice_id: str
    stability: float = 0.5
    similarity_boost: float = 0.75


class VeoRequest(BaseModel):
    prompt: str
    duration_seconds: int = 5
    aspect_ratio: str = "16:9"


# ── Gemini Chat ───────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Multi-turn chat via Gemini Flash/Pro.
    Used by: lesson assistant, script editor assistant, code assistant.
    """
    proxy = AIProxyService(db, UsageTracker(redis))
    messages = [
        {"role": m.role, "parts": [{"text": m.text}]}
        for m in body.messages
    ]
    return await proxy.gemini_chat(
        student_id=current_user.id,
        messages=messages,
        model=body.model,
        system_prompt=body.system_prompt,
    )


# ── Gemini Imagen ─────────────────────────────────────────────────────────────

@router.post("/imagen")
async def imagen(
    body: ImagenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Generate images via Imagen 3.
    Returns Gemini's response including base64 image data.
    """
    proxy = AIProxyService(db, UsageTracker(redis))
    return await proxy.gemini_imagen(
        student_id=current_user.id,
        prompt=body.prompt,
        sample_count=body.sample_count,
        aspect_ratio=body.aspect_ratio,
        model=body.model,
    )


# ── Gemini TTS ────────────────────────────────────────────────────────────────

@router.post("/tts/gemini")
async def tts_gemini(
    body: TTSRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Text-to-speech via Gemini 2.5 Flash TTS."""
    proxy = AIProxyService(db, UsageTracker(redis))
    return await proxy.gemini_tts(
        student_id=current_user.id,
        text=body.text,
        voice_name=body.voice_name,
    )


# ── ElevenLabs TTS ────────────────────────────────────────────────────────────

@router.post("/tts/elevenlabs")
async def tts_elevenlabs(
    body: ElevenLabsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Text-to-speech via ElevenLabs.
    Returns raw MP3 audio directly — frontend receives audio/mpeg.
    """
    proxy = AIProxyService(db, UsageTracker(redis))
    audio_bytes = await proxy.elevenlabs_tts(
        student_id=current_user.id,
        text=body.text,
        voice_id=body.voice_id,
        stability=body.stability,
        similarity_boost=body.similarity_boost,
    )
    return Response(content=audio_bytes, media_type="audio/mpeg")


# ── Google Veo ────────────────────────────────────────────────────────────────

@router.post("/veo")
async def veo_generate(
    body: VeoRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """
    Start a Veo 2 video generation. Returns a long-running operation name.
    Poll /ai/veo/poll/{operation_name} to check for completion.
    """
    proxy = AIProxyService(db, UsageTracker(redis))
    return await proxy.gemini_veo(
        student_id=current_user.id,
        prompt=body.prompt,
        duration_seconds=body.duration_seconds,
        aspect_ratio=body.aspect_ratio,
    )


@router.get("/veo/poll/{operation_name:path}")
async def veo_poll(
    operation_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Poll a Veo long-running operation for completion."""
    proxy = AIProxyService(db, UsageTracker(redis))
    return await proxy.gemini_veo_poll(
        student_id=current_user.id,
        operation_name=operation_name,
    )
