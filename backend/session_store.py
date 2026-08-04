"""Redis-backed conversation state for multi-worker deployments."""
import json
from typing import Any

import redis
from redis.exceptions import LockError
from redis.lock import Lock

from config import settings

class SessionStore:
    def __init__(self) -> None:
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def _key(self, kind: str, session_id: str) -> str:
        return f"career_coach:session:{kind}:{session_id}"

    def save(self, kind: str, session_id: str, payload: dict[str, Any]) -> None:
        self.client.setex(self._key(kind, session_id), settings.session_ttl_seconds, json.dumps(payload, ensure_ascii=False))

    def load(self, kind: str, session_id: str) -> dict[str, Any] | None:
        value = self.client.get(self._key(kind, session_id))
        return json.loads(value) if value else None

    def delete(self, kind: str, session_id: str) -> None:
        self.client.delete(self._key(kind, session_id))

    def acquire_lock(self, kind: str, session_id: str) -> Lock | None:
        lock = self.client.lock(
            f"{self._key(kind, session_id)}:lock",
            timeout=settings.session_lock_timeout_seconds,
            blocking=False,
            thread_local=False,
        )
        return lock if lock.acquire(blocking=False) else None

    @staticmethod
    def release_lock(lock: Lock) -> None:
        try:
            if lock.owned():
                lock.release()
        except LockError:
            pass

session_store = SessionStore()
