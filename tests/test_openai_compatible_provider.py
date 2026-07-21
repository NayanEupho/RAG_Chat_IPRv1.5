import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest

from backend.config import OllamaConfig
from backend.llm.client import OpenAICompatibleChatModel, normalize_engine


def test_openai_compatible_engine_aliases_normalize():
    assert normalize_engine("litellm") == "openai-compatible"
    assert normalize_engine("vllm") == "openai-compatible"
    assert normalize_engine("openai-compatible") == "openai-compatible"
    assert normalize_engine("ollama") == "ollama"


def test_openai_compatible_chat_payload_omits_ollama_only_fields(monkeypatch):
    monkeypatch.delenv("RAG_OPENAI_COMPAT_JSON_RESPONSE_FORMAT", raising=False)
    endpoint = OllamaConfig(host="http://litellm.local:4000/v1", model_name="qwen2.5-7b", api_key="sk-test")
    model = OpenAICompatibleChatModel(endpoint=endpoint, temperature=0.2, max_tokens=256)

    payload = model._payload(
        [
            {"role": "system", "content": "Stable system prompt."},
            {"role": "user", "content": "Hello"},
        ],
        stream=True,
        response_format="json",
    )

    assert payload["model"] == "qwen2.5-7b"
    assert payload["stream"] is True
    assert payload["max_tokens"] == 256
    assert "num_ctx" not in payload
    assert "num_predict" not in payload
    assert "keep_alive" not in payload
    assert "reasoning" not in payload
    assert "chat_template_kwargs" not in payload
    assert "response_format" not in payload


def test_openai_compatible_json_response_format_is_opt_in(monkeypatch):
    monkeypatch.setenv("RAG_OPENAI_COMPAT_JSON_RESPONSE_FORMAT", "true")
    endpoint = OllamaConfig(host="http://litellm.local:4000/v1", model_name="qwen2.5-7b", api_key="sk-test")
    model = OpenAICompatibleChatModel(endpoint=endpoint, temperature=0.2, max_tokens=256)

    payload = model._payload(
        [{"role": "user", "content": "Return JSON."}],
        stream=False,
        response_format="json",
    )

    assert payload["response_format"] == {"type": "json_object"}


def test_reload_config_reapplies_explicit_model_env(monkeypatch):
    from backend import config as config_module

    config_module._runtime_config.main_model = OllamaConfig(host="http://old-host", model_name="old-model")
    config_module._runtime_config.embedding_model = OllamaConfig(host="http://old-embed", model_name="old-embed")
    monkeypatch.setenv("RAG_MAIN_HOST", "http://litellm.local:4000/v1")
    monkeypatch.setenv("RAG_MAIN_MODEL", "qwen2.5-7b")
    monkeypatch.setenv("RAG_MAIN_ENGINE", "litellm")
    monkeypatch.setenv("RAG_MAIN_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_EMBED_HOST", "http://embed-host")
    monkeypatch.setenv("RAG_EMBED_MODEL", "embed-model")

    cfg = config_module.reload_config()

    assert cfg.main_model.host == "http://litellm.local:4000/v1"
    assert cfg.main_model.model_name == "qwen2.5-7b"
    assert cfg.main_model.api_key == "sk-test"
    assert cfg.main_engine == "litellm"


@pytest.mark.asyncio
async def test_openai_compatible_health_reports_routable_not_loaded(monkeypatch):
    import backend.llm.health as health

    async def listed(host: str, model_name: str, api_key: str = "") -> bool:
        assert host == "http://litellm.local:4000/v1"
        assert model_name == "qwen2.5-7b"
        assert api_key == "sk-test"
        return True

    monkeypatch.setattr(health, "_is_openai_model_listed", listed)

    result = await health._probe_model(
        "main",
        OllamaConfig(host="http://litellm.local:4000/v1", model_name="qwen2.5-7b", api_key="sk-test"),
        "litellm",
    )

    assert result.engine == "openai-compatible"
    assert result.listed is True
    assert result.loaded is None
    assert result.query_ready is True
    assert result.error is None