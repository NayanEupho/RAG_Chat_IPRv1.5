"""
Ollama API Client Wrapper
-------------------------
Manages connections to Ollama for both chat (inference) and embedding tasks.
Includes intelligent client caching per event loop and LangChain integration.
"""

import ollama
import asyncio
import weakref
import logging
from langchain_ollama import ChatOllama
from backend.config import get_config
from typing import Dict

logger = logging.getLogger(__name__)

# Cache for AsyncClient instances to prevent connection leakage across loops
_loop_client_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

# Singleton cache for ChatOllama instances (keyed by model name)
_chat_model_cache: Dict[str, ChatOllama] = {}

class OllamaClientWrapper:
    """
    Factory for retrieving pre-configured Ollama clients.
    Adapts client creation to the current execution context (async vs sync).
    """
    @classmethod
    def get_client(cls, host: str) -> ollama.AsyncClient:
        """
        Get or create an AsyncClient for the given host, cached per event loop.
        This respects event-loop binding requirements while avoiding repeated
        connection setup overhead at high QPS.
        """
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
    def get_embedding_client(cls) -> ollama.AsyncClient:
        config = get_config()
        if not config.embedding_model:
            raise ValueError("Embedding Model not configured")
        return cls.get_client(config.embedding_model.host)

    @staticmethod
    def get_chat_model_name() -> str:
        config = get_config()
        return config.main_model.model_name if config.main_model else ""

    @classmethod
    def get_chat_model(cls) -> ChatOllama:
        cfg = get_config()
        if not cfg.main_model:
            raise ValueError("Main Model not configured")
        disable_thinking = cfg.no_thinking or cfg.is_thinking_model
        model_key = (
            f"{cfg.main_model.host}:{cfg.main_model.model_name}:"
            f"think={not disable_thinking}:ctx={cfg.model_context_window}:"
            f"predict={cfg.num_predict}:temp={cfg.temperature}"
        )
        if model_key not in _chat_model_cache:
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
                logger.info(f"[CLIENT] RAG_NO_THINKING=True - sending Ollama think=false for {cfg.main_model.model_name}")
            elif cfg.is_thinking_model:
                logger.info(f"[CLIENT] Auto-detected thinking model: {cfg.main_model.model_name} - sending Ollama think=false")
            if disable_thinking:
                # ChatOllama maps `reasoning=False` to the Ollama API field `think: false`.
                kwargs["reasoning"] = False
            _chat_model_cache[model_key] = ChatOllama(**kwargs)
        return _chat_model_cache[model_key]

    @staticmethod
    def get_embedding_model_name() -> str:
        config = get_config()
        return config.embedding_model.model_name if config.embedding_model else ""
