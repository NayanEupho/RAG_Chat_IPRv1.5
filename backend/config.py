from pydantic import BaseModel
from typing import Optional

class OllamaConfig(BaseModel):
    host: str
    model_name: str

class AppConfig(BaseModel):
    main_model: Optional[OllamaConfig] = None
    embedding_model: Optional[OllamaConfig] = None
    
    @property
    def is_configured(self) -> bool:
        return self.main_model is not None and self.embedding_model is not None

import os

# Singleton instance
_runtime_config = AppConfig()

def get_config() -> AppConfig:
    # If not configured in memory, check env vars (in case of uvicorn worker)
    if not _runtime_config.is_configured:
        main_host = os.getenv("RAG_MAIN_HOST")
        main_model = os.getenv("RAG_MAIN_MODEL")
        embed_host = os.getenv("RAG_EMBED_HOST")
        embed_model = os.getenv("RAG_EMBED_MODEL")
        
        if main_host and main_model and embed_host and embed_model:
            _runtime_config.main_model = OllamaConfig(host=main_host, model_name=main_model)
            _runtime_config.embedding_model = OllamaConfig(host=embed_host, model_name=embed_model)
            
    return _runtime_config

def set_main_model(host: str, model: str):
    _runtime_config.main_model = OllamaConfig(host=host, model_name=model)

def set_embedding_model(host: str, model: str):
    _runtime_config.embedding_model = OllamaConfig(host=host, model_name=model)
