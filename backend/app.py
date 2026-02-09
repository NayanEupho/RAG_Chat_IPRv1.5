"""
FastAPI Backend Application
---------------------------
Initializes the web server, handles CORS, and manages the lifecycle of background services.
The application entry point includes the automatic startup of the file watchdog service.
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from backend.config import get_config
import logging

# Configure application-wide logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_chat_ipr")

from backend.ingestion.watcher import WatchdogService

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
    
    # Start Watchdog
    global watchdog_service
    watchdog_service = WatchdogService(watch_dir="upload_docs")
    watchdog_service.start()
    
    yield
    
    # Cleanup
    if watchdog_service:
        watchdog_service.stop()

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="RAG Chat IPR", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For dev only, use ["http://localhost:3000"] in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.api.routes import router as api_router
app.include_router(api_router, prefix="/api")

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
