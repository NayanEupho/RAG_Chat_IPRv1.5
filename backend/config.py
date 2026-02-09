"""
Configuration Management Module
-------------------------------
Handles application-wide settings using Pydantic for validation.
Supports loading from environment variables and provides a singleton configuration instance.
"""

from pydantic import BaseModel, field_validator
from typing import Optional
import os
import logging

# Initialize logger
logger = logging.getLogger(__name__)

class OllamaConfig(BaseModel):
    """Configuration for a specific Ollama host and model."""
    host: str
    model_name: str

class AppConfig(BaseModel):
    """
    Global Application Configuration.
    Stores model settings, workflow preferences, and hardware optimization flags.
    """
    main_model: Optional[OllamaConfig] = None
    embedding_model: Optional[OllamaConfig] = None
    
    # RAG Workflow Mode: Determines the architectural graph structure.
    # Options:
    # 1. "fused" (Default): Uses a single 'Planner' node for routing/rewriting/planning. 
    #    - Fastest (1 LLM call vs 3). 
    #    - Requires a smarter model (e.g., 72B).
    # 2. "modular" (Legacy): Uses separate Router -> Rewriter -> Retriever nodes.
    #    - Slower (3 sequential LLM calls).
    #    - More stable for smaller models (e.g., 7B) that struggle with complex instructions.
    rag_workflow: str = "fused"

    # Hardware Scaling
    ingest_force_cpu: bool = False
    
    # RAG Tuning
    reranker_model: str = "ms-marco-TinyBERT-L-2-v2"
    rag_confidence_threshold: float = 0.85
    retrieval_top_k: int = 7

    # VLM Extraction Options (Optional)
    vlm_host: str = "http://localhost:11434"
    vlm_model: str = "False"
    vlm_prompt: str = "auto"

    @field_validator("rag_workflow")
    @classmethod
    def validate_workflow(cls, v):
        v = v.lower()
        if v not in ["fused", "modular"]:
            return "modular"  # Default to Safe Mode if invalid
        return v

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
    
    # Always check for RAG_WORKFLOW env var (can be set independently)
    _runtime_config.rag_workflow = os.getenv("RAG_WORKFLOW", _runtime_config.rag_workflow).lower()
    
    # Audit Refinements: Centralized settings (with safety guards)
    force_cpu_env = os.getenv("INGEST_FORCE_CPU")
    if force_cpu_env:
        _runtime_config.ingest_force_cpu = force_cpu_env.lower() == "true"
        
    _runtime_config.reranker_model = os.getenv("RAG_RERANKER_MODEL", _runtime_config.reranker_model)
    
    try:
        _runtime_config.rag_confidence_threshold = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", str(_runtime_config.rag_confidence_threshold)))
    except ValueError:
        logger.warning("Invalid RAG_CONFIDENCE_THRESHOLD in env. Using default.")
        
    try:
        _runtime_config.retrieval_top_k = int(os.getenv("RAG_RETRIEVAL_TOP_K", str(_runtime_config.retrieval_top_k)))
    except ValueError:
        logger.warning("Invalid RAG_RETRIEVAL_TOP_K in env. Using default.")
    
    # VLM Sync
    _runtime_config.vlm_host = os.getenv("RAG_VLM_HOST", _runtime_config.vlm_host)
    _runtime_config.vlm_model = os.getenv("RAG_VLM_MODEL", _runtime_config.vlm_model)
    _runtime_config.vlm_prompt = os.getenv("RAG_VLM_PROMPT", _runtime_config.vlm_prompt)
            
    return _runtime_config

def set_main_model(host: str, model: str):
    _runtime_config.main_model = OllamaConfig(host=host, model_name=model)

def set_embedding_model(host: str, model: str):
    _runtime_config.embedding_model = OllamaConfig(host=host, model_name=model)

def set_rag_workflow(workflow: str):
    """Sets the RAG workflow mode (fused or modular)."""
    _runtime_config.rag_workflow = workflow.lower()
