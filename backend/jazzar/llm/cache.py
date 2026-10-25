"""Cache sémantique Redis : une question proche d'une question déjà répondue (cosinus >= seuil)
est servie sans appel LLM. Les filtres font partie de la clé (une même question sur 1945-1950
et sur 1960-1965 n'a pas la même réponse).
"""

from __future__ import annotations

import hashlib
import json
import uuid

import numpy as np
import redis.asyncio as redis

from jazzar.config import get_settings
from jazzar.logging import get_logger

log = get_logger(__name__)

INDEX_KEY = "jazzar:scache:index"
ENTRY_PREFIX = "jazzar:scache:entry:"
MAX_SCAN = 500  # entrées récentes comparées (suffisant pour un usage mono-tenant)


class SemanticCache:
    def __init__(self) -> None:
        s = get_settings()
        self.threshold = s.semantic_cache_threshold
        self.ttl = s.semantic_cache_ttl
        self._redis = redis.from_url(s.redis_url, decode_responses=True)
        self.enabled = True

    @staticmethod
    def _scope(filters: dict, lang: str) -> str:
        return hashlib.sha1(json.dumps({"f": filters, "l": lang}, sort_keys=True).encode()).hexdigest()[:12]

    async def lookup(self, question: str, embedding: list[float], filters: dict, lang: str) -> dict | None:
        if not self.enabled:
            return None
        try:
            scope = self._scope(filters, lang)
            ids = await self._redis.lrange(INDEX_KEY + ":" + scope, 0, MAX_SCAN - 1)
            if not ids:
                return None
            pipe = self._redis.pipeline()
            for i in ids:
                pipe.hgetall(ENTRY_PREFIX + i)
            entries = await pipe.execute()
            q = np.asarray(embedding, dtype=np.float32)
            best, best_sim = None, 0.0
            for i, e in zip(ids, entries, strict=True):
                if not e:
                    continue
                if e.get("question") == question:
                    return self._payload(e, 1.0)
                v = np.asarray(json.loads(e["embedding"]), dtype=np.float32)
                sim = float(np.dot(q, v))
                if sim > best_sim:
                    best, best_sim = e, sim
            if best is not None and best_sim >= self.threshold:
                log.info("scache.hit", sim=round(best_sim, 4), cached_question=best.get("question"))
                return self._payload(best, best_sim)
            return None
        except (redis.RedisError, OSError) as exc:
            log.warning("scache.unavailable", error=str(exc))
            self.enabled = False
            return None

    @staticmethod
    def _payload(e: dict, sim: float) -> dict:
        return {
            "answer": e["answer"],
            "citations": json.loads(e.get("citations", "[]")),
            "route": e.get("route"),
            "cached_question": e.get("question"),
            "similarity": sim,
        }

    async def store(self, question: str, embedding: list[float], filters: dict, lang: str, answer: str, citations: list, route: str) -> None:
        if not self.enabled:
            return
        try:
            scope = self._scope(filters, lang)
            cid = uuid.uuid4().hex
            await self._redis.hset(
                ENTRY_PREFIX + cid,
                mapping={
                    "question": question,
                    "embedding": json.dumps([round(x, 6) for x in embedding]),
                    "answer": answer,
                    "citations": json.dumps(citations),
                    "route": route,
                },
            )
            await self._redis.expire(ENTRY_PREFIX + cid, self.ttl)
            await self._redis.lpush(INDEX_KEY + ":" + scope, cid)
            await self._redis.ltrim(INDEX_KEY + ":" + scope, 0, MAX_SCAN - 1)
            await self._redis.expire(INDEX_KEY + ":" + scope, self.ttl)
        except (redis.RedisError, OSError) as exc:
            log.warning("scache.store_failed", error=str(exc))

    async def clear(self) -> int:
        n = 0
        async for key in self._redis.scan_iter("jazzar:scache:*"):
            await self._redis.delete(key)
            n += 1
        return n

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except (redis.RedisError, OSError):
            return False


_cache: SemanticCache | None = None


def get_cache() -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
