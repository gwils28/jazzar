"""Client Claude unique pour tout Jazzar.

- Résolution des identifiants par le SDK (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN ou profil `ant auth login`).
- Chaque appel est tracé dans `llm_calls` (tokens, cache, coût, latence, request-id).
- `fallbacks="default"` activé sur Opus (bascule serveur en cas de refus par les classificateurs).
- Mode dégradé : si aucune clé n'est disponible, `available` est False et les appelants basculent
  sur la recherche par mots-clés (fail-open).
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from jazzar.config import get_settings
from jazzar.logging import get_logger

log = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMUnavailable(RuntimeError):
    """Aucun identifiant Anthropic valide : les appelants doivent fail-open."""


class LLMRefused(RuntimeError):
    """Le modèle a refusé (stop_reason=refusal) ou n'a pas produit de sortie structurée."""


def _credentials_present() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    profile_dir = os.path.expanduser("~/.config/anthropic")
    return os.path.isdir(profile_dir) and any(os.scandir(profile_dir))


class LLM:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.available = _credentials_present()
        self._client: anthropic.AsyncAnthropic | None = None
        if self.available:
            try:
                self._client = anthropic.AsyncAnthropic(max_retries=2, timeout=300.0)
            except anthropic.AnthropicError as exc:  # pragma: no cover
                log.warning("llm.init_failed", error=str(exc))
                self.available = False

    @property
    def client(self) -> anthropic.AsyncAnthropic:
        if not self.available or self._client is None:
            raise LLMUnavailable("Aucune clé Anthropic configurée (ANTHROPIC_API_KEY).")
        return self._client

    # ---- Coûts -------------------------------------------------------------------------------
    def cost_usd(self, model: str, usage: Any) -> float:
        price = self.settings.pricing.get(model)
        if not price or usage is None:
            return 0.0
        return (
            (usage.input_tokens or 0) * price["input"]
            + (usage.output_tokens or 0) * price["output"]
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * price["cache_read"]
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * price["cache_write"]
        ) / 1_000_000

    async def _record(self, purpose: str, model: str, message: Any, latency_ms: int, trace_id: str | None, meta: dict | None = None) -> float:
        from jazzar.db import get_session
        from jazzar.models import LLMCall

        usage = getattr(message, "usage", None)
        cost = self.cost_usd(model, usage)
        try:
            async with get_session() as session:
                session.add(
                    LLMCall(
                        trace_id=trace_id,
                        purpose=purpose,
                        model=getattr(message, "model", model) or model,
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                        cost_usd=cost,
                        latency_ms=latency_ms,
                        stop_reason=getattr(message, "stop_reason", None),
                        request_id=getattr(message, "_request_id", None),
                        meta=meta or {},
                    )
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001 - la trace ne doit jamais casser la requête
            log.warning("llm.record_failed", error=str(exc))
        log.info("llm.call", purpose=purpose, model=model, latency_ms=latency_ms, cost_usd=round(cost, 5),
                 in_tokens=getattr(usage, "input_tokens", None), out_tokens=getattr(usage, "output_tokens", None),
                 cache_read=getattr(usage, "cache_read_input_tokens", None))
        return cost

    def _is_opus(self, model: str) -> bool:
        return "opus" in model

    # ---- Appels ------------------------------------------------------------------------------
    async def complete(
        self,
        *,
        purpose: str,
        messages: list[dict],
        system: str | list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 16000,
        effort: str = "medium",
        tools: list | None = None,
        trace_id: str | None = None,
        cache_system: bool = True,
    ) -> Any:
        model = model or self.settings.model_large
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages,
                                  "output_config": {"effort": effort}}
        if system:
            if cache_system and isinstance(system, str):
                kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            else:
                kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        t0 = time.perf_counter()
        if self._is_opus(model):
            msg = await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            msg = await self.client.messages.create(**kwargs)
        latency = int((time.perf_counter() - t0) * 1000)
        cost = await self._record(purpose, model, msg, latency, trace_id)
        msg._jazzar_cost = cost  # type: ignore[attr-defined]
        return msg

    async def parse(
        self,
        *,
        purpose: str,
        messages: list[dict],
        output_format: type[T],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 4000,
        effort: str = "low",
        trace_id: str | None = None,
    ) -> tuple[T, float]:
        """Sortie structurée validée par Pydantic. Retourne (objet, coût)."""
        model = model or self.settings.model_small
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages,
                                  "output_format": output_format, "output_config": {"effort": effort}}
        if system:
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        t0 = time.perf_counter()
        msg = await self.client.messages.parse(**kwargs)
        latency = int((time.perf_counter() - t0) * 1000)
        cost = await self._record(purpose, model, msg, latency, trace_id)
        if msg.stop_reason == "refusal" or msg.parsed_output is None:
            raise LLMRefused(f"{purpose}: stop_reason={msg.stop_reason}")
        return msg.parsed_output, cost

    @asynccontextmanager
    async def stream(
        self,
        *,
        purpose: str,
        messages: list[dict],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 64000,
        effort: str = "medium",
        trace_id: str | None = None,
    ) -> AsyncIterator[Any]:
        """Flux texte. Le contexte renvoie le stream SDK ; à la sortie l'appel est tracé."""
        model = model or self.settings.model_large
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "messages": messages,
                                  "output_config": {"effort": effort}}
        if system:
            kwargs["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        t0 = time.perf_counter()
        if self._is_opus(model):
            cm = self.client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            cm = self.client.messages.stream(**kwargs)
        async with cm as stream:
            yield stream
            try:
                final = await stream.get_final_message()
            except Exception:  # noqa: BLE001
                final = None
        latency = int((time.perf_counter() - t0) * 1000)
        if final is not None:
            cost = await self._record(purpose, model, final, latency, trace_id)
            stream._jazzar_cost = cost  # type: ignore[attr-defined]
            stream._jazzar_final = final  # type: ignore[attr-defined]


@lru_cache
def get_llm() -> LLM:
    return LLM()
