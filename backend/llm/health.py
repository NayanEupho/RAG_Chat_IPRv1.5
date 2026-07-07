"""
Runtime model health checks.

Readiness is based on Ollama /api/ps so status polling never triggers a
generation or embedding request. Warmup paths are responsible for loading
models opportunistically.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from backend.config import OllamaConfig, get_config


class ModelUnavailableError(RuntimeError):
    """Raised when a required model path is not query-ready."""


@dataclass
class ModelProbeResult:
    role: str
    host: str | None
    model_name: str | None
    configured: bool
    listed: bool
    loaded: bool | None
    query_ready: bool
    latency_ms: int
    checked_at: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_health_lock = asyncio.Lock()
_health_cache: dict[str, Any] | None = None
_health_cache_at = 0.0
_background_refresh_task: asyncio.Task | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _health_ttl_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("RAG_HEALTH_TTL_SECONDS", "15")))
    except ValueError:
        return 15.0


def _probe_timeout_seconds() -> float:
    try:
        return max(0.5, float(os.getenv("RAG_HEALTH_TIMEOUT_SECONDS", "2.5")))
    except ValueError:
        return 2.5


def _stale_ready_seconds() -> float:
    try:
        return max(_health_ttl_seconds(), float(os.getenv("RAG_HEALTH_STALE_READY_SECONDS", "300")))
    except ValueError:
        return 300.0


def _cache_age_seconds(now: float | None = None) -> float:
    if not _health_cache_at:
        return float("inf")
    return (now if now is not None else time.monotonic()) - _health_cache_at


def _cached_snapshot(*, cached: bool = True, refresh_in_progress: bool = False) -> dict[str, Any] | None:
    if not _health_cache:
        return None
    snapshot = dict(_health_cache)
    snapshot["cached"] = cached
    snapshot["cache_age_seconds"] = round(_cache_age_seconds(), 3)
    if refresh_in_progress:
        snapshot["refresh_in_progress"] = True
    return snapshot


def _snapshot_rag_ready(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    embedding = snapshot.get("embedding_model") or {}
    return bool(snapshot.get("rag_available") and embedding.get("query_ready"))


def _snapshot_embedding_ready(snapshot: dict[str, Any] | None) -> bool:
    if not snapshot:
        return False
    embedding = snapshot.get("embedding_model") or {}
    return bool(embedding.get("query_ready"))


def _model_matches(configured_name: str, discovered_name: str) -> bool:
    configured = configured_name.strip()
    discovered = discovered_name.strip()
    return (
        configured == discovered
        or configured.split(":")[0] == discovered.split(":")[0]
    )


async def _fetch_ollama_models(host: str, endpoint: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_probe_timeout_seconds()) as client:
        response = await client.get(f"{host.rstrip('/')}{endpoint}")
        response.raise_for_status()
        data = response.json()
    return data.get("models", []) if isinstance(data, dict) else []


async def _is_listed(host: str, model_name: str) -> bool:
    models = await _fetch_ollama_models(host, "/api/tags")
    return any(_model_matches(model_name, str(model.get("name", ""))) for model in models)


async def _is_loaded_best_effort(host: str, model_name: str) -> bool | None:
    models = await _fetch_ollama_models(host, "/api/ps")
    return any(_model_matches(model_name, str(model.get("name", ""))) for model in models)


async def _probe_model(role: str, model: OllamaConfig | None) -> ModelProbeResult:
    start = time.monotonic()
    checked_at = _utc_now()
    if model is None:
        return ModelProbeResult(
            role=role,
            host=None,
            model_name=None,
            configured=False,
            listed=False,
            loaded=False,
            query_ready=False,
            latency_ms=0,
            checked_at=checked_at,
            error="Model is not configured",
        )

    listed = False
    loaded: bool | None = None
    query_ready = False
    error: str | None = None
    try:
        listed_result, loaded_result = await asyncio.gather(
            _is_listed(model.host, model.model_name),
            _is_loaded_best_effort(model.host, model.model_name),
            return_exceptions=True,
        )
        listed = False if isinstance(listed_result, Exception) else bool(listed_result)
        loaded = False if isinstance(loaded_result, Exception) else bool(loaded_result)
        if loaded:
            query_ready = True
            error = None
        elif listed:
            error = f"Model '{model.model_name}' is listed but not loaded"
        else:
            error = f"Model '{model.model_name}' is not listed or loaded on host"
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__

    return ModelProbeResult(
        role=role,
        host=model.host,
        model_name=model.model_name,
        configured=True,
        listed=listed,
        loaded=loaded,
        query_ready=query_ready,
        latency_ms=int((time.monotonic() - start) * 1000),
        checked_at=checked_at,
        error=error,
    )


def _build_snapshot(main: ModelProbeResult, embedding: ModelProbeResult, cached: bool) -> dict[str, Any]:
    chat_available = main.query_ready
    rag_available = main.query_ready and embedding.query_ready
    status = "ok" if rag_available else "degraded" if chat_available else "offline"
    return {
        "status": status,
        "chat_available": chat_available,
        "rag_available": rag_available,
        "cached": cached,
        "main_model": main.to_dict(),
        "embedding_model": embedding.to_dict(),
        "main_model_healthy": main.query_ready,
        "main_model_error": main.error,
        "main_model_name": main.model_name or "Not Configured",
        "embed_model_healthy": embedding.query_ready,
        "embed_model_error": embedding.error,
        "embed_model_name": embedding.model_name or "Not Configured",
    }


async def get_model_health(force: bool = False) -> dict[str, Any]:
    """Return cached health unless stale or explicitly forced."""
    global _health_cache, _health_cache_at

    now = time.monotonic()
    if not force and _health_cache and (now - _health_cache_at) < _health_ttl_seconds():
        snapshot = _cached_snapshot()
        return snapshot or {}

    if _health_lock.locked() and _health_cache:
        snapshot = _cached_snapshot(refresh_in_progress=True)
        return snapshot or {}

    async with _health_lock:
        now = time.monotonic()
        if not force and _health_cache and (now - _health_cache_at) < _health_ttl_seconds():
            snapshot = _cached_snapshot()
            return snapshot or {}

        cfg = get_config()
        main, embedding = await asyncio.gather(
            _probe_model("main", cfg.main_model),
            _probe_model("embedding", cfg.embedding_model),
        )
        _health_cache = _build_snapshot(main, embedding, cached=False)
        _health_cache_at = time.monotonic()
        return dict(_health_cache)


async def _background_refresh() -> None:
    try:
        await get_model_health(force=True)
    except Exception:
        # Health refresh is best-effort; callers still fail closed on unavailable cache.
        return


def schedule_model_health_refresh() -> bool:
    """Refresh model health out of band when a stale-ready cache is used."""
    global _background_refresh_task

    if _health_lock.locked():
        return False
    if _background_refresh_task and not _background_refresh_task.done():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    _background_refresh_task = loop.create_task(_background_refresh())
    return True


async def ensure_rag_ready() -> dict[str, Any]:
    """Fail closed before retrieval if embeddings are unavailable."""
    now = time.monotonic()
    cached_snapshot = _cached_snapshot()
    if _snapshot_embedding_ready(cached_snapshot):
        age = _cache_age_seconds(now)
        if age <= _health_ttl_seconds():
            return cached_snapshot or {}
        if age <= _stale_ready_seconds():
            schedule_model_health_refresh()
            cached_snapshot = cached_snapshot or {}
            cached_snapshot["stale_ready_accepted"] = True
            return cached_snapshot

    snapshot = await get_model_health(force=False)
    embedding = snapshot.get("embedding_model") or {}
    if embedding.get("query_ready"):
        return snapshot

    reason = embedding.get("error") or "Embedding model is not query-ready"
    raise ModelUnavailableError(
        f"RAG is unavailable because the embedding model is not query-ready: {reason}"
    )


def invalidate_model_health_cache() -> None:
    global _health_cache, _health_cache_at, _background_refresh_task
    if _background_refresh_task and not _background_refresh_task.done():
        _background_refresh_task.cancel()
    _health_cache = None
    _health_cache_at = 0.0
    _background_refresh_task = None
