import ollama
from langchain_ollama import ChatOllama
from backend.config import get_config
from typing import Dict

class OllamaClientWrapper:
    # Removed global cache to prevent event loop mismatch between 
    # main thread (API) and worker thread (Watcher).
    # _clients: Dict[str, ollama.AsyncClient] = {}

    @classmethod
    def get_client(cls, host: str) -> ollama.AsyncClient:
        # Always create a new client to ensure it binds to the current event loop
        return ollama.AsyncClient(host=host)

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
