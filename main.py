import uvicorn
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.startup import run_interactive_config
from backend.config import get_config

def main():
    # 1. Run Interactive Configuration
    try:
        run_interactive_config()
    except KeyboardInterrupt:
        print("\nStartup cancelled.")
        return

    # 2. Check if configured
    config = get_config()
    if not config.is_configured:
        print("Configuration failed. Exiting.")
        return

    # 3. Start API Server
    print("Starting API Server...")
    
    # Pass config to uvicorn subprocess via environment variables
    os.environ["RAG_MAIN_HOST"] = config.main_model.host
    os.environ["RAG_MAIN_MODEL"] = config.main_model.model_name
    os.environ["RAG_EMBED_HOST"] = config.embedding_model.host
    os.environ["RAG_EMBED_MODEL"] = config.embedding_model.model_name
    
    # VLM config (optional - only if configured)
    if config.vlm_model:
        os.environ["RAG_VLM_HOST"] = config.vlm_model.host
        os.environ["RAG_VLM_MODEL"] = config.vlm_model.model_name
    
    # We run uvicorn programmatically
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)

if __name__ == "__main__":
    main()
