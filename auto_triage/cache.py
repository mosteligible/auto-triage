from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from auto_triage.config import Settings
from auto_triage.security import secret_value

logger = logging.getLogger(__name__)


class CacheClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def get_json(self, key: str) -> dict[str, Any] | None:
        if not self.settings.redis_cache_enabled:
            return None

        client = self._client()
        try:
            cached = await client.get(key)
        except RedisError:
            logger.warning("redis cache read failed", exc_info=True)
            return None
        finally:
            await client.aclose()

        if not cached:
            return None
        try:
            payload = json.loads(cached)
        except json.JSONDecodeError:
            logger.warning("redis cache payload was not valid json", extra={"cache_key": key})
            return None
        return payload if isinstance(payload, dict) else None

    async def set_json(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        if not self.settings.redis_cache_enabled or ttl_seconds <= 0:
            return

        client = self._client()
        try:
            await client.setex(key, ttl_seconds, json.dumps(payload, default=str))
        except RedisError:
            logger.warning("redis cache write failed", exc_info=True)
        finally:
            await client.aclose()

    def _client(self) -> Redis:
        if self.settings.redis_url:
            return Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                socket_timeout=self.settings.redis_timeout_seconds,
                socket_connect_timeout=self.settings.redis_timeout_seconds,
            )

        return Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            db=self.settings.redis_db,
            username=self.settings.redis_username,
            password=secret_value(self.settings.redis_password),
            decode_responses=True,
            socket_timeout=self.settings.redis_timeout_seconds,
            socket_connect_timeout=self.settings.redis_timeout_seconds,
        )
