import pytest

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
