"""
FastAPI Backend Application
---------------------------
Initializes the web server, handles CORS, and manages the lifecycle of background services.
The application entry point includes the automatic startup of the file watchdog service.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.admin.router import router as admin_router
from backend.api.routes import router as api_router
from backend.config import get_config
from backend.ingestion.watcher import WatchdogService
from backend.saml.routes import router as saml_router

# Configure application-wide logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_chat_ipr")

# Global service instance for the file system monitor
watchdog_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifespan Context Manager.
    Handles startup logic (config validation, service initialization)
    and shutdown logic (resource cleanup).
    """
    # check config on startup
    config = get_config()
    if not config.is_configured:
        logger.error("Application not configured! Please run via main.py wizard.")
        raise RuntimeError("Application not configured")
    
    logger.info(f"Main Model: {config.main_model.host} / {config.main_model.model_name}")
    logger.info(f"Embedding Model: {config.embedding_model.host} / {config.embedding_model.model_name}")
    logger.info(f"Model Context Window: {config.model_context_window} tokens")
    logger.info(f"RAG Workflow: {config.rag_workflow}")

    # Auto-detect model capabilities (context window, thinking model)
    try:
        from backend.llm.detection import detect_model_capabilities
        await detect_model_capabilities(config)
    except Exception as e:
        logger.warning(f"Model capability detection failed: {e}")
    logger.info(f"Post-detection — Context Window: {config.model_context_window}, Is Thinking: {config.is_thinking_model}")

    # Initialize the LLM client without blocking API startup. The actual
    # model/vector warmup is scheduled below as a best-effort background task.
    try:
        from backend.llm.client import OllamaClientWrapper
        OllamaClientWrapper.get_chat_model()
        logger.info("Chat model client initialized; model warmup scheduled in background")
    except Exception as e:
        logger.warning(f"Chat model client initialization failed: {e}")

    # Pre-warm Reranker to avoid cold-start latency on first query
    try:
        from backend.rag.reranker import Reranker
        reranker = Reranker()
        logger.info(f"Reranker pre-warmed: {reranker.model_name}")
    except Exception as e:
        logger.warning(f"Reranker pre-warm failed: {e}")
    
    # Initialize history DB
    try:
        from backend.state.history import init_history_db
        init_history_db()
        logger.info("History DB initialized")
    except Exception as e:
        logger.warning(f"History DB init failed: {e}")

    # Initialize isolated admin dashboard storage and local worker.
    try:
        from backend.admin.db import init_admin_db
        from backend.admin.worker import admin_worker
        init_admin_db()
        admin_worker.start()
        recovered = admin_worker.recover_incomplete_jobs()
        if recovered["requeued"] or recovered["skipped"]:
            logger.info(
                "Admin dashboard job recovery: requeued=%s skipped=%s",
                len(recovered["requeued"]),
                len(recovered["skipped"]),
            )
        logger.info("Admin dashboard DB initialized")
    except Exception as e:
        logger.warning(f"Admin dashboard init failed: {e}")

    # Start Watchdog
    global watchdog_service
    watchdog_service = WatchdogService(watch_dir="upload_docs")
    watchdog_service.start()

    try:
        from backend.llm.warmup import run_warmup
        app.state.model_warmup_task = asyncio.create_task(run_warmup(mode="all", source="startup"))
    except Exception as e:
        logger.warning(f"Startup warmup scheduling failed: {e}")
    
    yield
    
    # Cleanup
    if watchdog_service:
        watchdog_service.stop()
    try:
        from backend.admin.worker import admin_worker
        admin_worker.stop()
    except Exception as e:
        logger.warning(f"Admin dashboard worker shutdown failed: {e}")

app = FastAPI(title="RAG Chat IPR", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev only, use ["http://localhost:3000"] in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

app.include_router(admin_router, prefix="/api/v1")

app.include_router(saml_router, prefix="/saml")

# NEW: include SAML router
#from backend.saml.routes import router as saml_router
#app.include_router(saml_router)

@app.get("/")
async def root():
    config = get_config()
    return {
        "status": "running",
        "config": {
            "main_host": config.main_model.host if config.main_model else None,
            "embedding_host": config.embedding_model.host if config.embedding_model else None
        }
    }
