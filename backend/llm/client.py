"""
Model API client wrapper
------------------------
Keeps the historical OllamaClientWrapper facade while routing calls to either
Ollama or OpenAI-compatible providers such as LiteLLM/vLLM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import weakref
from typing import Any, Dict, Iterable

import httpx
import ollama
from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from backend.config import OllamaConfig, get_config

logger = logging.getLogger(__name__)

# Cache for AsyncClient instances to prevent connection leakage across loops
_loop_client_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_sync_embedding_client_cache: Dict[str, Any] = {}

# Singleton cache for chat model instances (keyed by endpoint/model/settings)
_chat_model_cache: Dict[str, Any] = {}

_OPENAI_COMPATIBLE_ENGINES = {"litellm", "openai", "openai-compatible", "openai_compatible", "vllm"}


def normalize_engine(engine: str | None) -> str:
    normalized = (engine or "ollama").strip().lower()
    if normalized in {"openai-compatible", "openai_compatible", "litellm", "vllm"}:
        return "openai-compatible"
    return normalized or "ollama"


def _openai_base_url(host: str) -> str:
    base = host.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def _openai_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _message_to_dict(message: Any) -> dict[str, str]:
    if isinstance(message, dict):
        role = str(message.get("role") or "user")
        content = message.get("content") or ""
        return {"role": role, "content": str(content)}

    role = "user"
    message_type = getattr(message, "type", "")
    if message_type == "system":
        role = "system"
    elif message_type in {"ai", "assistant"}:
        role = "assistant"
    return {"role": role, "content": str(getattr(message, "content", ""))}


def _messages_to_payload(messages: Iterable[Any]) -> list[dict[str, str]]:
    return [_message_to_dict(message) for message in messages]


def _choice_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def _embedding_values(data: dict[str, Any]) -> list[list[float]]:
    values = data.get("data") or []
    embeddings: list[list[float]] = []
    for item in values:
        vector = item.get("embedding") if isinstance(item, dict) else None
        if vector:
            embeddings.append(vector)
    return embeddings


class OpenAICompatibleChatModel:
    """Minimal async chat model compatible with current graph call sites."""

    def __init__(self, *, endpoint: OllamaConfig, temperature: float, max_tokens: int):
        self.endpoint = endpoint
        self.base_url = _openai_base_url(endpoint.host)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_json_response_format = (
            os.getenv("RAG_OPENAI_COMPAT_JSON_RESPONSE_FORMAT", "false").strip().lower() == "true"
        )
        self._sync_http_client = httpx.Client(timeout=None, trust_env=False)
        self._async_http_client = httpx.AsyncClient(timeout=None, trust_env=False)
        self._chat = ChatOpenAI(
            model=endpoint.model_name,
            base_url=self.base_url,
            api_key=endpoint.api_key or "not-needed",
            temperature=temperature,
            max_completion_tokens=max_tokens,
            streaming=True,
            http_client=self._sync_http_client,
            http_async_client=self._async_http_client,
        )

    def _payload(self, messages: Iterable[Any], *, stream: bool, response_format: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.endpoint.model_name,
            "messages": _messages_to_payload(messages),
            "stream": stream,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if response_format == "json" and self.enable_json_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def ainvoke(self, messages: Iterable[Any], **kwargs: Any) -> AIMessage:
        chat = self._chat
        if kwargs.get("format") == "json" and self.enable_json_response_format:
            chat = chat.bind(response_format={"type": "json_object"})
        return await chat.ainvoke(list(messages))

    async def astream(self, messages: Iterable[Any], **_: Any):
        async for chunk in self._chat.astream(list(messages)):
            yield chunk


class OpenAICompatibleAsyncEmbeddingClient:
    def __init__(self, endpoint: OllamaConfig):
        self.endpoint = endpoint
        self.base_url = _openai_base_url(endpoint.host)

    async def embed(self, *, model: str, input: str | list[str], **_: Any) -> dict[str, list[list[float]]]:
        payload = {"model": model, "input": input}
        async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=_openai_headers(self.endpoint.api_key),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return {"embeddings": _embedding_values(data)}


class OpenAICompatibleSyncClient:
    def __init__(self, endpoint: OllamaConfig):
        self.endpoint = endpoint
        self.base_url = _openai_base_url(endpoint.host)
        timeout = httpx.Timeout(connect=10.0, read=float(os.getenv("ADMIN_EMBED_READ_TIMEOUT_SECONDS", "120")), write=30.0, pool=5.0)
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def embed(self, *, model: str, input: str | list[str], **_: Any) -> dict[str, list[list[float]]]:
        response = self._client.post(
            f"{self.base_url}/embeddings",
            headers=_openai_headers(self.endpoint.api_key),
            json={"model": model, "input": input},
        )
        response.raise_for_status()
        return {"embeddings": _embedding_values(response.json())}

    def chat(self, *, model: str, messages: list[dict[str, str]], stream: bool = False, options: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        options = options or {}
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "temperature": options.get("temperature", 0),
            "max_tokens": options.get("num_predict") or options.get("max_tokens") or 4096,
        }
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers=_openai_headers(self.endpoint.api_key),
            json=payload,
        )
        response.raise_for_status()
        content = _choice_content(response.json())
        return {"message": {"content": content}}


class OllamaClientWrapper:
    """
    Factory for retrieving pre-configured model clients.

    The class name is retained for compatibility with existing call sites and
    tests. Ollama remains the default behavior when RAG_*_ENGINE is omitted.
    """

    @classmethod
    def get_client(cls, host: str) -> ollama.AsyncClient:
        """Get or create an Ollama AsyncClient for the given host."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return ollama.AsyncClient(host=host)

        if loop not in _loop_client_cache:
            _loop_client_cache[loop] = {}

        loop_clients = _loop_client_cache[loop]

        if host not in loop_clients:
            loop_clients[host] = ollama.AsyncClient(host=host)

        return loop_clients[host]

    @classmethod
    def get_chat_client(cls) -> ollama.AsyncClient:
        config = get_config()
        if not config.main_model:
            raise ValueError("Main Model not configured")
        return cls.get_client(config.main_model.host)

    @classmethod
    def get_embedding_client(cls) -> Any:
        config = get_config()
        if not config.embedding_model:
            raise ValueError("Embedding Model not configured")
        if normalize_engine(config.embedding_engine) == "ollama":
            return cls.get_client(config.embedding_model.host)
        return OpenAICompatibleAsyncEmbeddingClient(config.embedding_model)

    @classmethod
    def get_sync_embedding_client(cls) -> Any:
        config = get_config()
        if not config.embedding_model:
            raise ValueError("Embedding Model not configured")
        engine = normalize_engine(config.embedding_engine)
        key = f"{engine}:{config.embedding_model.host}:{config.embedding_model.model_name}:{bool(config.embedding_model.api_key)}"
        if key not in _sync_embedding_client_cache:
            if engine == "ollama":
                _sync_embedding_client_cache[key] = ollama.Client(host=config.embedding_model.host)
            else:
                _sync_embedding_client_cache[key] = OpenAICompatibleSyncClient(config.embedding_model)
        return _sync_embedding_client_cache[key]

    @staticmethod
    def get_chat_model_name() -> str:
        config = get_config()
        return config.main_model.model_name if config.main_model else ""

    @classmethod
    def get_chat_model(cls) -> Any:
        cfg = get_config()
        if not cfg.main_model:
            raise ValueError("Main Model not configured")
        engine = normalize_engine(cfg.main_engine)
        disable_thinking = engine == "ollama" and (cfg.no_thinking or cfg.is_thinking_model)
        model_key = (
            f"{engine}:{cfg.main_model.host}:{cfg.main_model.model_name}:"
            f"key={bool(cfg.main_model.api_key)}:think={not disable_thinking}:ctx={cfg.model_context_window}:"
            f"predict={cfg.num_predict}:temp={cfg.temperature}"
        )
        if model_key not in _chat_model_cache:
            if engine == "ollama":
                kwargs = dict(
                    base_url=cfg.main_model.host,
                    model=cfg.main_model.model_name,
                    streaming=True,
                    num_ctx=cfg.model_context_window,
                    num_predict=cfg.num_predict,
                    temperature=cfg.temperature,
                    keep_alive=-1,
                )
                if cfg.no_thinking:
                    logger.info("[CLIENT] RAG_NO_THINKING=True - sending Ollama think=false for %s", cfg.main_model.model_name)
                elif cfg.is_thinking_model:
                    logger.info("[CLIENT] Auto-detected thinking model: %s - sending Ollama think=false", cfg.main_model.model_name)
                if disable_thinking:
                    # ChatOllama maps `reasoning=False` to the Ollama API field `think: false`.
                    kwargs["reasoning"] = False
                _chat_model_cache[model_key] = ChatOllama(**kwargs)
            elif engine == "openai-compatible":
                logger.info("[CLIENT] Using OpenAI-compatible chat endpoint for %s", cfg.main_model.model_name)
                _chat_model_cache[model_key] = OpenAICompatibleChatModel(
                    endpoint=cfg.main_model,
                    temperature=cfg.temperature,
                    max_tokens=cfg.num_predict,
                )
            else:
                raise ValueError(f"Unsupported main model engine: {cfg.main_engine}")
        return _chat_model_cache[model_key]

    @staticmethod
    def get_embedding_model_name() -> str:
        config = get_config()
        return config.embedding_model.model_name if config.embedding_model else ""

    @staticmethod
    def get_embedding_keep_alive() -> float | str | None:
        config = get_config()
        if normalize_engine(config.embedding_engine) != "ollama":
            return None
        raw_value = os.getenv("RAG_EMBED_KEEP_ALIVE", "-1").strip()
        try:
            return float(raw_value)
        except ValueError:
            return raw_value