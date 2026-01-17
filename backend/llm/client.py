import ollama
import asyncio
import weakref
from langchain_ollama import ChatOllama
from backend.config import get_config
from typing import Dict

# Cache AsyncClient instances per event loop to avoid repeated connection setup.
# Uses WeakKeyDictionary so clients are garbage-collected when the loop is gone.
_loop_client_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

class OllamaClientWrapper:
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
            # No running loop - create a new client (useful for ingestion worker thread)
            return ollama.AsyncClient(host=host)
        
        # Get or create the host->client mapping for this loop
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
        config = get_config()
        if not config.main_model:
            raise ValueError("Main Model not configured")
        return ChatOllama(
            base_url=config.main_model.host,
            model=config.main_model.model_name,
            streaming=True
        )

    @staticmethod
    def get_embedding_model_name() -> str:
        config = get_config()
        return config.embedding_model.model_name if config.embedding_model else ""
