"""
Non-blocking warmup coordinator.

Warmups are intentionally best-effort. They should reduce cold path latency,
but must never block user input or compete heavily with live chat requests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import contextmanager
from threading import Lock
from typing import Any

from backend.llm.health import get_model_health

logger = logging.getLogger(__name__)

_active_request_lock = Lock()
_active_request_count = 0
_warmup_lock = asyncio.Lock()
_cancel_generation = 0


def real_request_active() -> bool:
    with _active_request_lock:
        return _active_request_count > 0


@contextmanager
def real_request_scope():
    """Mark a real chat stream as active so warmups skip or stop early."""
    global _active_request_count, _cancel_generation
    with _active_request_lock:
        _active_request_count += 1
        _cancel_generation += 1
    try:
        yield
    finally:
        with _active_request_lock:
            _active_request_count = max(0, _active_request_count - 1)


def _cancel_token() -> int:
    with _active_request_lock:
        return _cancel_generation


def _was_cancelled(token: int) -> bool:
    with _active_request_lock:
        return token != _cancel_generation or _active_request_count > 0


async def _warm_chat_model(cancel_token: int) -> str:
    if _was_cancelled(cancel_token):
        return "skipped"
    from backend.llm.client import OllamaClientWrapper

    chat_model = OllamaClientWrapper.get_chat_model()
    await chat_model.ainvoke([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Reply with OK only."},
    ])
    return "ready"


async def _warm_embedding_model(cancel_token: int) -> str:
    if _was_cancelled(cancel_token):
        return "skipped"
    from backend.config import get_config
    from backend.llm.client import OllamaClientWrapper

    cfg = get_config()
    if not cfg.embedding_model:
        return "not_configured"
    client = OllamaClientWrapper.get_embedding_client()
    response = await client.embed(model=cfg.embedding_model.model_name, input="warmup")
    embeddings = response.get("embeddings", []) if isinstance(response, dict) else getattr(response, "embeddings", [])
    return "ready" if embeddings else "empty"


async def _warm_vector_store(filename: str | None, cancel_token: int) -> str:
    if _was_cancelled(cancel_token):
        return "skipped"
    from backend.rag.store import get_vector_store

    store = get_vector_store()
    files = await asyncio.to_thread(store.get_all_files)
    if _was_cancelled(cancel_token):
        return "skipped"
    if not files:
        return "empty"

    target = filename if filename in files else files[0]
    await asyncio.to_thread(
        store.get_by_metadata,
        {"filename": {"$eq": target}},
        1,
    )
    return "ready"


async def run_warmup(mode: str = "all", filename: str | None = None, source: str = "api") -> dict[str, Any]:
    normalized_mode = (mode or "all").lower()
    if normalized_mode not in {"all", "chat", "rag", "doc"}:
        normalized_mode = "all"

    if real_request_active():
        return {"status": "skipped", "reason": "active_request", "mode": normalized_mode}
    if _warmup_lock.locked():
        return {"status": "skipped", "reason": "warmup_in_progress", "mode": normalized_mode}

    async with _warmup_lock:
        if real_request_active():
            return {"status": "skipped", "reason": "active_request", "mode": normalized_mode}

        cancel_token = _cancel_token()
        start = time.monotonic()
        result: dict[str, Any] = {
            "status": "completed",
            "mode": normalized_mode,
            "source": source,
            "chat": "not_requested",
            "rag": "not_requested",
            "vector": "not_requested",
        }

        try:
            if normalized_mode in {"all", "chat"}:
                result["chat"] = await _warm_chat_model(cancel_token)

            if normalized_mode in {"all", "rag", "doc"} and not _was_cancelled(cancel_token):
                result["rag"] = await _warm_embedding_model(cancel_token)
                health = await get_model_health(force=True)
                if result["rag"] == "ready" and not health.get("rag_available"):
                    result["rag"] = "unavailable"
                if health.get("embed_model_error"):
                    result["embedding_error"] = health.get("embed_model_error")

            if normalized_mode in {"all", "doc"} and not _was_cancelled(cancel_token):
                result["vector"] = await _warm_vector_store(filename, cancel_token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("[WARMUP] Best-effort warmup failed: %s", exc)
            result["status"] = "failed"
            result["error"] = str(exc)
        finally:
            result["duration_ms"] = int((time.monotonic() - start) * 1000)

        if _was_cancelled(cancel_token):
            result["status"] = "skipped"
            result["reason"] = "real_request_started"
        return result
