"""
Rate limiter using Redis sliding window counters.

Each student gets a key per provider per day:
  webgenius:rl:{student_id}:{provider}:{YYYY-MM-DD}  →  integer count

On every proxied API call:
  1. Check current count against hard limit
  2. If over limit → raise 429, log usage row with status=rate_limited
  3. If under limit → increment counter, proceed with call
"""
from datetime import date
from typing import Optional
import redis.asyncio as aioredis
from fastapi import HTTPException, status
from app.core.config import settings


class RateLimiter:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    def _key(self, student_id: str, provider: str) -> str:
        today = date.today().isoformat()  # YYYY-MM-DD — resets at midnight UTC
        return f"webgenius:rl:{student_id}:{provider}:{today}"

    async def get_usage(self, student_id: str, provider: str) -> int:
        """Return how many calls this student has made today for a provider."""
        r = await self._get_redis()
        val = await r.get(self._key(student_id, provider))
        return int(val) if val else 0

    async def check_and_increment(
        self,
        student_id: str,
        provider: str,
        limit: int,
        units: int = 1,
    ) -> int:
        """
        Atomically check limit and increment if allowed.
        Returns the new count after increment.
        Raises HTTP 429 if limit would be exceeded.
        `units` lets image grid calls count as 4 instead of 1.
        """
        r = await self._get_redis()
        key = self._key(student_id, provider)

        # Lua script: atomic check-then-increment
        lua_script = """
        local current = tonumber(redis.call('GET', KEYS[1])) or 0
        local limit = tonumber(ARGV[1])
        local units = tonumber(ARGV[2])
        if current + units > limit then
            return -1
        end
        local new_val = redis.call('INCRBY', KEYS[1], units)
        -- Expire at end of day (86400s max, but set to 25h to handle clock skew)
        redis.call('EXPIRE', KEYS[1], 90000)
        return new_val
        """
        result = await r.eval(lua_script, 1, key, str(limit), str(units))

        if result == -1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "provider": provider,
                    "message": f"Daily limit of {limit} calls reached for {provider}. "
                               "Ask your teacher to adjust your limit.",
                },
            )
        return int(result)

    async def get_all_usage_today(self, student_id: str) -> dict[str, int]:
        """Return usage counts for all providers for a student today."""
        providers = ["gemini_text", "gemini_image", "elevenlabs", "runway", "openai"]
        r = await self._get_redis()
        keys = [self._key(student_id, p) for p in providers]
        values = await r.mget(*keys)
        return {p: int(v) if v else 0 for p, v in zip(providers, values)}

    async def reset_student(self, student_id: str, provider: Optional[str] = None):
        """
        Teacher-triggered reset. Clears today's counter for one or all providers.
        Useful when a student accidentally used up their limit.
        """
        r = await self._get_redis()
        if provider:
            await r.delete(self._key(student_id, provider))
        else:
            providers = ["gemini_text", "gemini_image", "elevenlabs", "runway", "openai"]
            keys = [self._key(student_id, p) for p in providers]
            await r.delete(*keys)

    async def close(self):
        if self._redis:
            await self._redis.aclose()


rate_limiter = RateLimiter()
