"""
Model Capability Detection
---------------------------
Probes the Ollama API to auto-detect model capabilities:
- Context window size (from model_info.{arch}.context_length)
- Thinking model support (from known thinking architectures)
"""

import logging
import os
import ollama

logger = logging.getLogger(__name__)

# Known thinking model architectures (from Ollama docs)
# These models emit a `thinking` field separating reasoning trace from answer.
_THINKING_ARCHITECTURES = {
    "qwen",
    "qwen2",       # Qwen 3 family
    "qwen3",
    "deepseek",    # DeepSeek R1, DeepSeek-v3.1
    "gpt-oss",     # GPT-OSS
    "qwq",         # QwQ
    "command-r7b", # Cohere Command R7B (if applicable)
}


async def detect_model_capabilities(config) -> None:
    """
    Probe the Ollama API for the main model and update config fields:
      - config.model_context_window
      - config.is_thinking_model

    Only overrides values NOT already set via explicit env vars.
    """
    if not config.main_model:
        logger.warning("[DETECT] No main model configured, skipping detection")
        return

    host = config.main_model.host
    model = config.main_model.model_name
    context_window_env = os.getenv("MODEL_CONTEXT_WINDOW")
    no_thinking_env = os.getenv("RAG_NO_THINKING")

    client = ollama.AsyncClient(host=host)
    try:
        info = await client.show(model=model)
    except Exception as e:
        logger.warning(f"[DETECT] Failed to fetch model info for {model}: {e}")
        return

    # The ollama Python library exposes modelinfo as a Pydantic attribute (dict-like)
    model_info = info.modelinfo or {}

    # --- Auto-detect context window ---
    architecture = model_info.get("general.architecture", "")
    if architecture:
        ctx_key = f"{architecture}.context_length"
        auto_ctx = model_info.get(ctx_key)
        if auto_ctx and not context_window_env:
            capped = min(auto_ctx, 16384)
            config.model_context_window = capped
            logger.info(f"[DETECT] Auto-detected context window for {architecture}: {auto_ctx} (capped to {capped}) tokens")
        elif auto_ctx and context_window_env:
            logger.info(f"[DETECT] Context window overridden by env: {context_window_env} (auto was {auto_ctx})")
        elif not auto_ctx:
            logger.info(f"[DETECT] Could not find context_length for arch '{architecture}', keeping default {config.model_context_window}")
    else:
        logger.info(f"[DETECT] No architecture info for {model}, keeping default context window {config.model_context_window}")

    # --- Auto-detect thinking model ---
    if no_thinking_env and no_thinking_env.lower() == "true":
        logger.info(f"[DETECT] RAG_NO_THINKING=true — skipping thinking auto-detect")
        return

    if architecture:
        arch_lower = architecture.lower()
        model_lower = model.lower()
        is_thinking = (
            arch_lower in _THINKING_ARCHITECTURES
            or model_lower.startswith(("qwen3", "qwen3."))
            or "qwen3" in model_lower
        )
        if is_thinking:
            config.is_thinking_model = True
            logger.info(f"[DETECT] Detected thinking model: {model} (arch: {architecture}) — will disable reasoning")
        else:
            logger.info(f"[DETECT] Model {model} (arch: {architecture}) is not a known thinking model")
