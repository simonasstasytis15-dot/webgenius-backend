import redis.asyncio as aioredis
from app.core.config import settings
from typing import Optional
import time

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


class UsageTracker:
    """
    Tracks per-student API usage in Redis.
    Keys follow: usage:{student_id}:{provider}:{YYYY-MM-DD}
    TTL is set to 48h so yesterday's data is still visible in dashboards.
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    def _key(self, student_id: str, provider: str) -> str:
        from datetime import date
        today = date.today().isoformat()
        return f"usage:{student_id}:{provider}:{today}"

    async def increment(self, student_id: str, provider: str) -> int:
        """Increment usage counter and return the new count."""
        key = self._key(student_id, provider)
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 172800)  # 48h TTL
        results = await pipe.execute()
        return results[0]

    async def get_today(self, student_id: str, provider: str) -> int:
        """Return today's usage count for a student/provider pair."""
        key = self._key(student_id, provider)
        val = await self.redis.get(key)
        return int(val) if val else 0

    async def get_all_today(self, student_id: str) -> dict:
        """Return today's usage across all providers for one student."""
        providers = ["gemini_text", "gemini_imagen", "gemini_tts", "gemini_veo", "elevenlabs"]
        counts = {}
        for p in providers:
            counts[p] = await self.get_today(student_id, p)
        return counts

    async def get_class_usage(self, student_ids: list[str]) -> dict:
        """Aggregate today's usage across all students in a class."""
        result = {}
        for sid in student_ids:
            result[sid] = await self.get_all_today(sid)
        return result
