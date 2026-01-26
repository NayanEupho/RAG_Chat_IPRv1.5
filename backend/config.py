from pydantic import BaseModel, field_validator
from typing import Optional

class OllamaConfig(BaseModel):
    host: str
    model_name: str

class AppConfig(BaseModel):
    main_model: Optional[OllamaConfig] = None
    embedding_model: Optional[OllamaConfig] = None
    vlm_model: Optional[OllamaConfig] = None  # VLM for OCR (DeepSeek, etc.)
    
    # RAG Workflow Mode: Determines the architectural graph structure.
    # Options:
    # 1. "fused" (Default): Uses a single 'Planner' node for routing/rewriting/planning. 
    #    - Fastest (1 LLM call vs 3). 
    #    - Requires a smarter model (e.g., 72B).
    # 2. "modular" (Legacy): Uses separate Router -> Rewriter -> Retriever nodes.
    #    - Slower (3 sequential LLM calls).
    #    - More stable for smaller models (e.g., 7B) that struggle with complex instructions.
    rag_workflow: str = "fused"
    
    # VLM Prompt Strategy: Determines how the VLM processes documents.
    # Options:
    # 1. "auto" (Default): Smart two-pass - extracts structure, then describes unlabeled visuals.
    # 2. "grounding": Single-pass document-to-markdown. Fastest.
    # 3. "describe": Single-pass detailed image description. Slowest but most thorough.
    # 4. "parse_figure": Single-pass for parsing figures/charts.
    vlm_prompt: str = "auto"

    @field_validator("rag_workflow")
    @classmethod
    def validate_workflow(cls, v):
        v = v.lower()
        if v not in ["fused", "modular"]:
            return "modular"  # Default to Safe Mode if invalid
        return v
    
    @field_validator("vlm_prompt")
    @classmethod
    def validate_vlm_prompt(cls, v):
        v = v.lower()
        if v not in ["auto", "grounding", "describe", "parse_figure"]:
            return "auto"  # Default to auto if invalid
        return v

    @property
    def is_configured(self) -> bool:
        return self.main_model is not None and self.embedding_model is not None
    
    @property
    def is_vlm_enabled(self) -> bool:
        """Check if VLM-based OCR is enabled and configured."""
        return self.vlm_model is not None

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
    
    # Load RAG workflow setting
    rag_workflow = os.getenv("RAG_WORKFLOW", "fused")
    _runtime_config.rag_workflow = rag_workflow.lower()
    
    # Load VLM Model (Vision-Language Model for OCR)
    # RAG_VLM_MODEL="False" means disabled (use Docling)
    # RAG_VLM_MODEL="deepseek-ocr" means use VLM OCR
    vlm_host = os.getenv("RAG_VLM_HOST")
    vlm_model = os.getenv("RAG_VLM_MODEL", "False")
    
    if vlm_model.lower() not in ["false", "0", "no", "off", ""]:
        if vlm_host:
            _runtime_config.vlm_model = OllamaConfig(host=vlm_host, model_name=vlm_model)
    else:
        _runtime_config.vlm_model = None  # Disabled
    
    # Load VLM Prompt Strategy
    vlm_prompt = os.getenv("RAG_VLM_PROMPT", "auto")
    _runtime_config.vlm_prompt = vlm_prompt.lower()
            
    return _runtime_config

def set_main_model(host: str, model: str):
    _runtime_config.main_model = OllamaConfig(host=host, model_name=model)

def set_embedding_model(host: str, model: str):
    _runtime_config.embedding_model = OllamaConfig(host=host, model_name=model)

def set_vlm_model(host: str, model: str):
    """Set VLM model for OCR. Pass model='False' to disable."""
    if model.lower() in ["false", "0", "no", "off", ""]:
        _runtime_config.vlm_model = None
    else:
        _runtime_config.vlm_model = OllamaConfig(host=host, model_name=model)

def set_vlm_strategy(prompt: str):
    """Set VLM prompt strategy (auto, grounding, describe, parse_figure)."""
    _runtime_config.vlm_prompt = prompt.lower()

def set_rag_workflow(mode: str):
    """Set RAG workflow mode (fused or modular)."""
    if mode.lower() in ["fused", "modular"]:
        _runtime_config.rag_workflow = mode.lower()
    else:
        _runtime_config.rag_workflow = "modular"  # Default safe mode
