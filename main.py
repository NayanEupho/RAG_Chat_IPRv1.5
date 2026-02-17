"""
RAG Chat Entry Point
--------------------
Main entry point for the RAG Chat application.
Handles interactive configuration and starts the Uvicorn API server.
"""

import uvicorn
import sys
import os
from dotenv import load_dotenv

# Load environment variables globally
load_dotenv()

# Ensure project root is in path for imports to work correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.startup import run_interactive_config
from backend.config import get_config

def main():
    """
    Primary execution flow:
    1. Runs interactive configuration wizard if needed.
    2. Validates the configuration.
    3. Starts the Uvicorn server with appropriate environment variables.
    """
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
    os.environ["RAG_WORKFLOW"] = config.rag_workflow
    os.environ["INGEST_FORCE_CPU"] = str(config.ingest_force_cpu).lower()
    
    # We run uvicorn programmatically
    port = int(os.getenv("RAG_PORT", "8000"))
    logger_level = "info"
    
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True, forwarded_allow_ips="*", log_level=logger_level)

if __name__ == "__main__":
    main()
