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
from dotenv import load_dotenv

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
    normalization_model: Optional[OllamaConfig] = None
    main_engine: str = "ollama"
    embedding_engine: str = "ollama"
    normalization_engine: str = "ollama"
    vlm_engine: str = "ollama"
    
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
    ingest_llm_normalize: bool = False

    # Authentication
    use_saml_login: bool = False
    
    # RAG Tuning
    reranker_model: str = "ms-marco-TinyBERT-L-2-v2"
    rag_confidence_threshold: float = 0.85
    retrieval_top_k: int = 5
    retrieval_detail_top_k: int = 8
    retrieval_deep_top_k: int = 10
    retrieval_candidate_multiplier: int = 7
    retrieval_min_score: float = 0.05
    parsing_mode: str = "auto"

    # VLM Extraction Options (Optional)
    vlm_host: str = "http://localhost:11434"
    vlm_model: str = "False"
    vlm_prompt: str = "auto"
    vlm_dpi: int = 220
    vlm_timeout_seconds: int = 300
    vlm_concurrency: int = 1
    vlm_retries: int = 1

    # Model Context Window (for dynamic token budget)
    # Auto-detected from Ollama model metadata at startup, override via MODEL_CONTEXT_WINDOW env var
    # Default is conservative (16K) — models like Nemotron-3 support 262K but allocating
    # the full KV cache on a 120B model is extremely memory-heavy and slows TTFT.
    model_context_window: int = 16384

    # Thinking model flag: auto-detected from Ollama model metadata at startup.
    # When True, ChatOllama is created with reasoning=False to skip thinking tokens.
    is_thinking_model: bool = False

    # Force-disable reasoning for all models (env RAG_NO_THINKING).
    # When True, ChatOllama is created with reasoning=False regardless of auto-detect.
    no_thinking: bool = False
    num_predict: int = 512
    temperature: float = 0.2

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

    @property
    def docling_force_cpu(self) -> bool:
        """Backward-compatible alias for older tests/scripts."""
        return self.ingest_force_cpu

import os

# Singleton instance
_runtime_config = AppConfig()

def get_config() -> AppConfig:
    # Load .env file if present (supports uvicorn workers that may not inherit shell env vars)
    load_dotenv()
    # If not configured in memory, check env vars (in case of uvicorn worker)
    if not _runtime_config.is_configured:
        main_host = os.getenv("RAG_MAIN_HOST")
        main_model = os.getenv("RAG_MAIN_MODEL")
        embed_host = os.getenv("RAG_EMBED_HOST")
        embed_model = os.getenv("RAG_EMBED_MODEL")
        if main_host and main_model and embed_host and embed_model:
            _runtime_config.main_model = OllamaConfig(host=main_host, model_name=main_model)
            _runtime_config.embedding_model = OllamaConfig(host=embed_host, model_name=embed_model)

    normalize_host = os.getenv("RAG_NORMALIZATION_HOST")
    normalize_model = os.getenv("RAG_NORMALIZATION_MODEL")
    if not _runtime_config.normalization_model and normalize_host and normalize_model:
        _runtime_config.normalization_model = OllamaConfig(host=normalize_host, model_name=normalize_model)
    elif not _runtime_config.normalization_model and _runtime_config.main_model:
        _runtime_config.normalization_model = _runtime_config.main_model
    
    # Always check for RAG_WORKFLOW env var (can be set independently)
    _runtime_config.rag_workflow = os.getenv("RAG_WORKFLOW", _runtime_config.rag_workflow).lower()
    
    # Audit Refinements: Centralized settings (with safety guards)
    force_cpu_env = os.getenv("INGEST_FORCE_CPU")
    if force_cpu_env:
        _runtime_config.ingest_force_cpu = force_cpu_env.lower() == "true"

    llm_normalize_env = os.getenv("INGEST_LLM_NORMALIZE")
    if llm_normalize_env:
        _runtime_config.ingest_llm_normalize = llm_normalize_env.lower() == "true"
        
    saml_login_env = os.getenv("USE_SAML_LOGIN")
    if saml_login_env:
        _runtime_config.use_saml_login = saml_login_env.lower() == "true"
        logger.info(f"[CONFIG] USE_SAML_LOGIN set from env: {saml_login_env} -> {_runtime_config.use_saml_login}")
    
    logger.info(f"[CONFIG] get_config() returning use_saml_login={_runtime_config.use_saml_login}")
        
    _runtime_config.reranker_model = os.getenv("RAG_RERANKER_MODEL", _runtime_config.reranker_model)
    _runtime_config.main_engine = os.getenv("RAG_MAIN_ENGINE", _runtime_config.main_engine).lower()
    _runtime_config.embedding_engine = os.getenv("RAG_EMBED_ENGINE", _runtime_config.embedding_engine).lower()
    _runtime_config.normalization_engine = os.getenv("RAG_NORMALIZATION_ENGINE", _runtime_config.normalization_engine).lower()
    _runtime_config.vlm_engine = os.getenv("RAG_VLM_ENGINE", _runtime_config.vlm_engine).lower()
    
    try:
        _runtime_config.rag_confidence_threshold = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", str(_runtime_config.rag_confidence_threshold)))
    except ValueError:
        logger.warning("Invalid RAG_CONFIDENCE_THRESHOLD in env. Using default.")
        
    try:
        _runtime_config.retrieval_top_k = int(os.getenv("RAG_RETRIEVAL_TOP_K", str(_runtime_config.retrieval_top_k)))
    except ValueError:
        logger.warning("Invalid RAG_RETRIEVAL_TOP_K in env. Using default.")

    try:
        _runtime_config.retrieval_detail_top_k = int(os.getenv("RAG_RETRIEVAL_DETAIL_TOP_K", str(_runtime_config.retrieval_detail_top_k)))
    except ValueError:
        logger.warning("Invalid RAG_RETRIEVAL_DETAIL_TOP_K in env. Using default.")

    try:
        _runtime_config.retrieval_deep_top_k = int(os.getenv("RAG_RETRIEVAL_DEEP_TOP_K", str(_runtime_config.retrieval_deep_top_k)))
    except ValueError:
        logger.warning("Invalid RAG_RETRIEVAL_DEEP_TOP_K in env. Using default.")

    try:
        _runtime_config.retrieval_candidate_multiplier = int(os.getenv("RAG_CANDIDATE_MULTIPLIER", str(_runtime_config.retrieval_candidate_multiplier)))
    except ValueError:
        logger.warning("Invalid RAG_CANDIDATE_MULTIPLIER in env. Using default.")

    try:
        _runtime_config.retrieval_min_score = float(os.getenv("RAG_RETRIEVAL_MIN_SCORE", str(_runtime_config.retrieval_min_score)))
    except ValueError:
        logger.warning("Invalid RAG_RETRIEVAL_MIN_SCORE in env. Using default.")

    parsing_mode = os.getenv("RAG_PARSING_MODE", _runtime_config.parsing_mode).lower()
    if parsing_mode not in {"auto", "pymupdf", "pymupdf4llm", "docling", "docling_vision", "llm", "vision_llm"}:
        logger.warning("Invalid RAG_PARSING_MODE in env. Using auto.")
        parsing_mode = "auto"
    _runtime_config.parsing_mode = parsing_mode
    
    # VLM Sync
    _runtime_config.vlm_host = os.getenv("RAG_VLM_HOST", _runtime_config.vlm_host)
    _runtime_config.vlm_model = os.getenv("RAG_VLM_MODEL", _runtime_config.vlm_model)
    _runtime_config.vlm_prompt = os.getenv("RAG_VLM_PROMPT", _runtime_config.vlm_prompt)
    try:
        _runtime_config.vlm_dpi = int(os.getenv("RAG_VLM_DPI", str(_runtime_config.vlm_dpi)))
    except ValueError:
        logger.warning("Invalid RAG_VLM_DPI in env. Using default.")
    try:
        _runtime_config.vlm_timeout_seconds = int(os.getenv("RAG_VLM_TIMEOUT_SECONDS", str(_runtime_config.vlm_timeout_seconds)))
    except ValueError:
        logger.warning("Invalid RAG_VLM_TIMEOUT_SECONDS in env. Using default.")
    try:
        _runtime_config.vlm_concurrency = int(os.getenv("RAG_VLM_CONCURRENCY", str(_runtime_config.vlm_concurrency)))
    except ValueError:
        logger.warning("Invalid RAG_VLM_CONCURRENCY in env. Using default.")
    try:
        _runtime_config.vlm_retries = int(os.getenv("RAG_VLM_RETRIES", str(_runtime_config.vlm_retries)))
    except ValueError:
        logger.warning("Invalid RAG_VLM_RETRIES in env. Using default.")

    # Model context window (env override takes priority)
    try:
        _runtime_config.model_context_window = int(os.getenv("MODEL_CONTEXT_WINDOW", str(_runtime_config.model_context_window)))
    except ValueError:
        logger.warning("Invalid MODEL_CONTEXT_WINDOW in env. Using default.")

    # No-thinking override (env takes priority over auto-detect)
    no_think_env = os.getenv("RAG_NO_THINKING")
    if no_think_env:
        _runtime_config.no_thinking = no_think_env.lower() == "true"
        if _runtime_config.no_thinking:
            logger.info("[CONFIG] RAG_NO_THINKING=true — forcing reasoning=False")
            
    try:
        _runtime_config.num_predict = int(os.getenv("RAG_NUM_PREDICT", str(_runtime_config.num_predict)))
    except ValueError:
        logger.warning("Invalid RAG_NUM_PREDICT in env. Using default.")

    try:
        _runtime_config.temperature = float(os.getenv("RAG_TEMPERATURE", str(_runtime_config.temperature)))
    except ValueError:
        logger.warning("Invalid RAG_TEMPERATURE in env. Using default.")

    return _runtime_config

def set_main_model(host: str, model: str):
    _runtime_config.main_model = OllamaConfig(host=host, model_name=model)

def set_embedding_model(host: str, model: str):
    _runtime_config.embedding_model = OllamaConfig(host=host, model_name=model)

def set_normalization_model(host: str, model: str):
    _runtime_config.normalization_model = OllamaConfig(host=host, model_name=model)

def set_rag_workflow(workflow: str):
    """Sets the RAG workflow mode (fused or modular)."""
    _runtime_config.rag_workflow = workflow.lower()
