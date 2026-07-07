import pytest
import time

from backend.config import AppConfig, OllamaConfig
from backend.llm.health import ModelUnavailableError


def _config():
    return AppConfig(
        main_model=OllamaConfig(host="http://main-host:11434", model_name="main-model"),
        embedding_model=OllamaConfig(host="http://embed-host:11434", model_name="embed-model"),
    )


async def _listed(host, model):
    return True


async def _loaded(host, model):
    return True


async def _embedding_not_loaded(host, model):
    return "embed" not in host


@pytest.mark.asyncio
async def test_health_requires_embedding_model_to_be_loaded(monkeypatch):
    import backend.llm.health as health

    health.invalidate_model_health_cache()
    monkeypatch.setattr(health, "get_config", _config)
    monkeypatch.setattr(health, "_is_listed", _listed)
    monkeypatch.setattr(health, "_is_loaded_best_effort", _embedding_not_loaded)

    snapshot = await health.get_model_health(force=True)

    assert snapshot["chat_available"] is True
    assert snapshot["rag_available"] is False
    assert snapshot["main_model_healthy"] is True
    assert snapshot["embed_model_healthy"] is False
    assert snapshot["embedding_model"]["listed"] is True
    assert "listed but not loaded" in snapshot["embed_model_error"]

    with pytest.raises(ModelUnavailableError):
        await health.ensure_rag_ready()


@pytest.mark.asyncio
async def test_health_reports_rag_available_when_both_models_are_query_ready(monkeypatch):
    import backend.llm.health as health

    health.invalidate_model_health_cache()
    monkeypatch.setattr(health, "get_config", _config)
    monkeypatch.setattr(health, "_is_listed", _listed)
    monkeypatch.setattr(health, "_is_loaded_best_effort", _loaded)

    snapshot = await health.get_model_health(force=True)

    assert snapshot["status"] == "ok"
    assert snapshot["chat_available"] is True
    assert snapshot["rag_available"] is True
    assert snapshot["embedding_model"]["loaded"] is True


@pytest.mark.asyncio
async def test_ensure_rag_ready_accepts_bounded_stale_ready_cache_without_probe(monkeypatch):
    import backend.llm.health as health

    health.invalidate_model_health_cache()
    monkeypatch.setenv("RAG_HEALTH_TTL_SECONDS", "1")
    monkeypatch.setenv("RAG_HEALTH_STALE_READY_SECONDS", "300")
    monkeypatch.setattr(health, "get_config", _config)
    monkeypatch.setattr(health, "_is_listed", _listed)
    monkeypatch.setattr(health, "_is_loaded_best_effort", _loaded)

    await health.get_model_health(force=True)
    monkeypatch.setattr(health, "_health_cache_at", time.monotonic() - 5)

    async def fail_if_probed(*args, **kwargs):
        raise AssertionError("stale-ready hot path should not probe Ollama")

    scheduled = {"value": False}

    def fake_schedule():
        scheduled["value"] = True
        return True

    monkeypatch.setattr(health, "_probe_model", fail_if_probed)
    monkeypatch.setattr(health, "schedule_model_health_refresh", fake_schedule)

    snapshot = await health.ensure_rag_ready()

    assert snapshot["embedding_model"]["query_ready"] is True
    assert snapshot["stale_ready_accepted"] is True
    assert scheduled["value"] is True


@pytest.mark.asyncio
async def test_ensure_rag_ready_accepts_stale_embedding_ready_even_when_main_unready(monkeypatch):
    import backend.llm.health as health

    health.invalidate_model_health_cache()
    monkeypatch.setenv("RAG_HEALTH_TTL_SECONDS", "1")
    monkeypatch.setenv("RAG_HEALTH_STALE_READY_SECONDS", "300")
    monkeypatch.setattr(health, "get_config", _config)
    monkeypatch.setattr(health, "_is_listed", _listed)

    async def main_unloaded_embedding_loaded(host, model):
        return "embed" in host

    monkeypatch.setattr(health, "_is_loaded_best_effort", main_unloaded_embedding_loaded)
    await health.get_model_health(force=True)
    monkeypatch.setattr(health, "_health_cache_at", time.monotonic() - 5)

    async def fail_if_probed(*args, **kwargs):
        raise AssertionError("embedding-ready retrieval gate should not probe main model health")

    monkeypatch.setattr(health, "_probe_model", fail_if_probed)
    monkeypatch.setattr(health, "schedule_model_health_refresh", lambda: True)

    snapshot = await health.ensure_rag_ready()

    assert snapshot["rag_available"] is False
    assert snapshot["embedding_model"]["query_ready"] is True
    assert snapshot["main_model"]["query_ready"] is False
    assert snapshot["stale_ready_accepted"] is True


@pytest.mark.asyncio
async def test_ensure_rag_ready_refreshes_and_fails_closed_when_cache_is_too_old(monkeypatch):
    import backend.llm.health as health

    health.invalidate_model_health_cache()
    monkeypatch.setenv("RAG_HEALTH_TTL_SECONDS", "1")
    monkeypatch.setenv("RAG_HEALTH_STALE_READY_SECONDS", "2")
    monkeypatch.setattr(health, "get_config", _config)
    monkeypatch.setattr(health, "_is_listed", _listed)
    monkeypatch.setattr(health, "_is_loaded_best_effort", _loaded)

    await health.get_model_health(force=True)
    monkeypatch.setattr(health, "_health_cache_at", time.monotonic() - 10)
    monkeypatch.setattr(health, "_is_loaded_best_effort", _embedding_not_loaded)

    with pytest.raises(ModelUnavailableError):
        await health.ensure_rag_ready()


@pytest.mark.asyncio
async def test_warmup_skips_while_real_request_is_active():
    from backend.llm.warmup import real_request_scope, run_warmup

    with real_request_scope():
        result = await run_warmup(mode="all", source="test")

    assert result["status"] == "skipped"
    assert result["reason"] == "active_request"


@pytest.mark.asyncio
async def test_retriever_fails_closed_when_rag_is_not_ready(monkeypatch):
    from backend.graph.nodes import retriever

    async def fail_ready():
        raise ModelUnavailableError("embedding model unavailable")

    monkeypatch.setattr(retriever, "ensure_rag_ready", fail_ready)

    with pytest.raises(ModelUnavailableError):
        await retriever.retrieve_documents({"query": "what is in the document?", "targeted_docs": []})
