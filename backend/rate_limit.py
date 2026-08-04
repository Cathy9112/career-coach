import redis
from fastapi import HTTPException, Request, status

from config import settings


class RateLimiter:
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def enforce(self, scope: str, identifier: str, limit: int, window_seconds: int) -> None:
        key = f"career_coach:rate:{scope}:{identifier}"
        count = self.client.incr(key)
        if count == 1:
            self.client.expire(key, window_seconds)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请稍后重试",
            )


def client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


rate_limiter = RateLimiter()
