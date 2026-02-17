from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from backend.graph.workflow import build_graph
from langchain_core.messages import HumanMessage, AIMessage
# For SAML
from fastapi import Depends
from backend.saml.auth import get_current_user, SAMLUser
#end SAML

import uuid
import json
import os
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy initialization of LangGraph workflow
# Avoids compilation at module import time before config is loaded
_graph_app = None

def get_graph():
    """Get or create the compiled LangGraph workflow."""
    global _graph_app
    if _graph_app is None:
        _graph_app = build_graph()
    return _graph_app

# We can compile it once globally or per request if state is managed externally.
# With MemorySaver checkpointer, we lazy-init for cleaner startup.
class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    mode: str = "auto" # 'auto', 'rag', 'chat'

class ChatResponse(BaseModel):
    response: str
    intent: str
    sources: List[str] = []

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, user: SAMLUser = Depends(get_current_user)):
    """
    Classic chat endpoint (Non-Streaming).
    """
    try:
        from backend.state.history import is_session_owner
        if not is_session_owner(request.session_id, user.user_id):
             # Ensure session exists (defaults to current user if new)
             # But if it's new, we should create it. 
             # For legacy/simple chat, we might just proceed if it's 'default'.
             # Matching working version logic:
             pass 
             # Wait, working version threw 403.
             # "if not is_session_owner... raise HTTPException"
             
        # Re-check working version logic from Step 193
        if not is_session_owner(request.session_id, user.user_id):
            raise HTTPException(status_code=403, detail="Not authorized to access this session")

        config = {"configurable": {"thread_id": request.session_id}}
        inputs = {
            "messages": [HumanMessage(content=request.message)],
            "mode": request.mode
        }
        final_state = await get_graph().ainvoke(inputs, config=config)
        
        messages = final_state.get('messages', [])
        response_text = "No response"
        if messages:
            last_message = messages[-1]
            response_text = last_message.content if isinstance(last_message, AIMessage) else str(last_message)
            
        return ChatResponse(
            response=response_text,
            intent=final_state.get('intent', 'unknown'),
            sources=final_state.get('documents', [])
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/stream")
async def chat_stream_endpoint(request_body: ChatRequest, request: Request, user: SAMLUser = Depends(get_current_user)):
    """
    Streaming chat endpoint with History Logging.
    """
    from backend.state.history import add_message, create_session, is_session_owner, get_session_owner
    
    # Ensure session exists
    # Check ownership
    actual_owner = get_session_owner(request_body.session_id)
    if actual_owner and actual_owner != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this session")

    create_session(request_body.session_id, user_id=user.user_id)
    
    # Log User Message Immediately
    add_message(request_body.session_id, "user", request_body.message)

    config = {"configurable": {"thread_id": request_body.session_id}}
    inputs = {
        "messages": [HumanMessage(content=request_body.message)],
        "mode": request_body.mode
    }

    async def sse_generator():
        full_response = ""
        final_intent = "unknown"
        final_docs = []
        thoughts = []
        
        try:
            initial_status = "Protocol Initiated"
            thoughts.append({"type": "status", "content": initial_status})
            yield f"event: status\ndata: {initial_status}\n\n"
            
            async for event in get_graph().astream_events(inputs, config=config, version="v1"):
                # CHECK FOR DISCONNECTION
                if await request.is_disconnected():
                    logger.info(f"[STREAM] Client disconnected for session {request_body.session_id}. Aborting graph execution.")
                    return

                event_type = event["event"]
                
                if event_type == "on_chain_start":
                    name = event["name"]
                    status_data = None
                    if name == "router":
                         status_data = "Analyzing Intent..."
                    elif name == "rewriter":
                         status_data = "Refining Contextual Query..."
                    elif name == "retriever":
                         status_data = "Searching Documents..."
                    elif name == "generator":
                         status_data = "Generating Answer..."
                    
                    if status_data:
                         # Append to persistence list
                         type_mapped = "thought" if "Analyzing" in status_data or "Generating" in status_data else "tool_call"
                         thoughts.append({"type": type_mapped, "content": status_data})
                         yield f"event: status\ndata: {status_data}\n\n"

                if event_type == "on_chat_model_stream":
                    meta = event.get("metadata", {})
                    node = meta.get("langgraph_node", "")
                    
                    if node == "generator":
                        chunk = event["data"]["chunk"]
                        if hasattr(chunk, 'content') and chunk.content:
                            import json
                            clean_token = json.dumps(chunk.content)
                            full_response += chunk.content
                            yield f"event: token\ndata: {clean_token}\n\n"
                    else:
                        logger.warning(f"[STREAM] Token received from unexpected node: {node}")

            # End of Stream, fetch final state
            final_state = await get_graph().aget_state(config)
            final_intent = final_state.values.get("intent", "unknown")
            final_docs = final_state.values.get("documents", [])
            targeted_docs = final_state.values.get("targeted_docs", [])
            
            # Pass documents exactly as retrieved
            deduped_docs = final_docs

            import json
            metadata = json.dumps({
                "intent": final_intent, 
                "sources": deduped_docs,
                "targeted_docs": targeted_docs
            })
            yield f"event: end\ndata: {metadata}\n\n"

            # Log Bot Response
            add_message(
                request_body.session_id, 
                "bot", 
                full_response, 
                final_intent, 
                deduped_docs, 
                metadata={"targeted_docs": targeted_docs},
                thoughts=thoughts
            )
        
        except Exception as e:
            logger.error(f"[STREAM] Error in sse_generator: {e}")
            yield f"event: error\ndata: {str(e)}\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(sse_generator(), media_type="text/event-stream")

class CreateSessionRequest(BaseModel):
    title: Optional[str] = None

@router.post("/sessions")
def create_session_endpoint(request: CreateSessionRequest, user: SAMLUser = Depends(get_current_user)):
    """Create a new chat session."""
    from backend.state.history import create_new_session
    return create_new_session(request.title, user_id=user.user_id)

@router.get("/sessions")
def get_sessions(user: SAMLUser = Depends(get_current_user)):
    """List all available chat sessions for the current user."""
    from backend.state.history import get_all_sessions
    return {"sessions": get_all_sessions(user_id=user.user_id)}

@router.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: str, user: SAMLUser = Depends(get_current_user)):
    """Delete a session permanently."""
    from backend.state.history import delete_session
    try:
        delete_session(session_id, user_id=user.user_id)
        return {"status": "deleted", "id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history/{session_id}")
def get_history(session_id: str, user: SAMLUser = Depends(get_current_user)):
    """Get full message history for a session."""
    from backend.state.history import get_session_history, get_session_owner
    
    # Security Check: Ensure user owns this session
    owner = get_session_owner(session_id)
    if owner and owner != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this session history")

    return {"messages": get_session_history(session_id)}

@router.get("/config")
def get_config_route():
    """Get current application configuration (Unified)."""
    from backend.config import get_config
    try:
        cfg = get_config()
        return {
            "main_model": cfg.main_model.model_name if cfg.main_model else None,
            "main_host": cfg.main_model.host if cfg.main_model else None,
            "embed_model": cfg.embedding_model.model_name if cfg.embedding_model else None,
            "embed_host": cfg.embedding_model.host if cfg.embedding_model else None,
            "rag_workflow": cfg.rag_workflow,
            "reranker_model": cfg.reranker_model,
            "rag_confidence_threshold": cfg.rag_confidence_threshold,
            "retrieval_top_k": cfg.retrieval_top_k,
            "ingest_force_cpu": cfg.ingest_force_cpu,
            "vlm_model": cfg.vlm_model
        }
    except Exception as e:
        return {"error": f"Config error: {str(e)}"}

@router.get("/status")
async def status():
    """
    Real-time health check for Ollama hosts and model availability.
    Updated to use AsyncClient for non-blocking I/O.
    """
    import httpx
    from backend.config import get_config
    
    async def check_model_health_async(host: str, model_name: str) -> dict:
        """Check if a specific model is available on a given Ollama host."""
        result = {"healthy": False, "error": None}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{host}/api/tags")
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("models", [])
                    # Check if model_name is in the list (strip version tags for comparison)
                    model_names = [m.get("name", "").split(":")[0] for m in models]
                    model_base = model_name.split(":")[0]
                    
                    if model_base in model_names or model_name in [m.get("name", "") for m in models]:
                        result["healthy"] = True
                    else:
                        result["error"] = f"Model '{model_name}' not found on host"
                else:
                    result["error"] = f"Host returned status {response.status_code}"
        except httpx.ConnectError:
            result["error"] = "Cannot connect to Ollama host"
        except httpx.TimeoutException:
            result["error"] = "Connection timed out"
        except Exception as e:
            result["error"] = str(e)
        return result
    
    try:
        cfg = get_config()
        
        # Check Main and Embedding models in parallel
        import asyncio
        main_task = check_model_health_async(cfg.main_model.host, cfg.main_model.model_name) if cfg.main_model else None
        embed_task = check_model_health_async(cfg.embedding_model.host, cfg.embedding_model.model_name) if cfg.embedding_model else None
        
        results = await asyncio.gather(*[t for t in [main_task, embed_task] if t])
        
        main_result = results[0] if main_task else {"healthy": False, "error": "Not configured"}
        embed_result = results[1] if embed_task else {"healthy": False, "error": "Not configured"}
        
        # Determine overall status
        if main_result["healthy"] and embed_result["healthy"]:
            overall_status = "ok"
        elif main_result["healthy"] or embed_result["healthy"]:
            overall_status = "degraded"
        else:
            overall_status = "offline"
        
        return {
            "status": overall_status,
            "main_model_healthy": main_result["healthy"],
            "main_model_error": main_result["error"],
            "main_model_name": cfg.main_model.model_name if cfg.main_model else "Not Configured",
            "embed_model_healthy": embed_result["healthy"],
            "embed_model_error": embed_result["error"],
            "embed_model_name": cfg.embedding_model.model_name if cfg.embedding_model else "Not Configured"
        }
    except Exception as e:
        return {
            "status": "offline",
            "main_model_healthy": False,
            "main_model_error": str(e),
            "embed_model_healthy": False,
            "embed_model_error": str(e)
        }


@router.get("/files/{filename}")
async def get_file(filename: str):
    """
    Securely serve a file from the upload_docs directory.
    Prevents path traversal and ensures only existing files are served.
    """
    # Security 1: Only allow filenames, no paths
    safe_filename = os.path.basename(filename)
    
    # Security 2: Whitelist allowed extensions
    ALLOWED_EXTENSIONS = {'.pdf', '.md', '.txt', '.png', '.jpg', '.jpeg', '.csv', '.xlsx'}
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="File type not allowed")

    # Security 3: Strict directory rooting
    base_dir = os.path.abspath("upload_docs")
    found_path = None
    
    for root, dirs, files in os.walk(base_dir):
        if safe_filename in files:
            target_path = os.path.join(root, safe_filename)
            # Security 4: Final verification that path is inside base_dir
            if os.path.abspath(target_path).startswith(base_dir):
                found_path = target_path
                break
            
    if not found_path or not os.path.exists(found_path):
        raise HTTPException(status_code=404, detail=f"Document not found")
        
    return FileResponse(found_path)

@router.get("/documents")
def get_documents():
    """List all unique filenames indexed in the vector store."""
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    return {"documents": store.get_all_files()}


@router.get("/login")
def saml_login(request: Request):
    print("login api callled.....")
#    auth = _get_saml_auth(request)
#    return_to = request.query_params.get("next", "/")
#    redirect_url = auth.login(return_to=return_to)
#    return RedirectResponse(redirect_url)
    return {"login": 1 }
