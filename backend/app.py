from fastapi import FastAPI
from contextlib import asynccontextmanager
from backend.config import get_config
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_chat_ipr")

from backend.ingestion.watcher import WatchdogService

# Global service instance
watchdog_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.get("/set_vlm_model")
async def set_vlm_model(host: str, model: str):
    """Set VLM model for OCR. Pass model='False' to disable."""
    if model.lower() in ["false", "0", "no", "off", ""]:
        _runtime_config.vlm_model = None
    else:
        _runtime_config.vlm_model = OllamaConfig(host=host, model_name=model)
    return {"message": f"VLM model set to {model} at {host}" if _runtime_config.vlm_model else "VLM model disabled"}

@app.get("/set_vlm_strategy")
async def set_vlm_strategy(prompt: str):
    """Set VLM prompt strategy (auto, grounding, describe, parse_figure)."""
    _runtime_config.vlm_prompt = prompt.lower()
    return {"message": f"VLM strategy set to {prompt.lower()}"}
