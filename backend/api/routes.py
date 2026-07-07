from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Optional
from backend.graph.workflow import build_graph
from langchain_core.messages import HumanMessage, AIMessage
# For SAML
from fastapi import Depends
from backend.saml.auth import get_current_user, SAMLUser
#end SAML

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
        from backend.config import get_config
        # In anonymous mode, skip ownership checks — all sessions are accessible
        if get_config().use_saml_login and not is_session_owner(request.session_id, user.user_id):
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
    from backend.state.history import add_message, create_session, get_recent_targeted_docs, get_session_owner
    
    # Ensure session exists
    # Check ownership (skip in anonymous mode)
    from backend.config import get_config
    actual_owner = get_session_owner(request_body.session_id)
    if get_config().use_saml_login and actual_owner and actual_owner != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this session")

    create_session(request_body.session_id, user_id=user.user_id)

    config = {"configurable": {"thread_id": request_body.session_id}}
    inputs = {
        "messages": [HumanMessage(content=request_body.message)],
        "mode": request_body.mode,
        "last_targeted_docs": get_recent_targeted_docs(request_body.session_id),
    }

    async def sse_generator():
        from backend.llm.warmup import real_request_scope
        request_scope = real_request_scope()
        request_scope.__enter__()
        logger.info(f"[STREAM] Starting SSE generator for session {request_body.session_id}")
        full_response = ""
        final_intent = "unknown"
        final_docs = []
        thoughts = []
        ttft_start = None
        ttft_logged = False
        user_message_logged = False
        node_starts = {}
        node_timings = {}
        generator_start_ms = None
        generator_first_token_ms = None
        
        try:
            # 1. Flush Padding (Immediate response to stop buffering in proxies)
            padding = ":" + (" " * 4096) + " padding to flush buffer\n\n"
            yield padding
            
            initial_status = "Protocol Initiated"
            thoughts.append({"type": "status", "content": initial_status})
            logger.info(f"[STREAM] Emitting status: {initial_status}")
            yield f"event: status\ndata: {initial_status}\n\n"
            
            import time
            ttft_start = time.monotonic()

            async for event in get_graph().astream_events(inputs, config=config, version="v1"):
                # CHECK FOR DISCONNECTION
                if await request.is_disconnected():
                    logger.info(f"[STREAM] Client disconnected for session {request_body.session_id}. Aborting graph execution.")
                    return

                event_type = event["event"]
                
                if event_type == "on_chain_start":
                    name = event["name"]
                    if ttft_start and name in {"router", "planner", "rewriter", "retriever", "generator"}:
                        node_starts[name] = time.monotonic()
                        node_timings.setdefault(name, {})["start_ms"] = int((node_starts[name] - ttft_start) * 1000)
                        if name == "generator":
                            generator_start_ms = node_timings[name]["start_ms"]
                    status_data = None
                    if name == "router" or name == "planner":
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
                         logger.info(f"[STREAM] Emitting status: {status_data}")
                         yield f"event: status\ndata: {status_data}\n\n"

                if event_type == "on_chain_end":
                    name = event["name"]
                    if ttft_start and name in node_starts:
                        elapsed_ms = int((time.monotonic() - node_starts[name]) * 1000)
                        node_timings.setdefault(name, {})["duration_ms"] = elapsed_ms
                        node_timings[name]["end_ms"] = int((time.monotonic() - ttft_start) * 1000)

                if event_type == "on_chat_model_stream":
                    meta = event.get("metadata", {})
                    node = meta.get("langgraph_node", "")
                    
                    if node == "generator":
                        chunk = event["data"]["chunk"]
                        if hasattr(chunk, 'content') and chunk.content:
                            import json
                            if not ttft_logged and ttft_start:
                                ttft_logged = True
                                ttft_ms = int((time.monotonic() - ttft_start) * 1000)
                                generator_first_token_ms = ttft_ms
                                if "generator" in node_timings:
                                    start_ms = node_timings["generator"].get("start_ms")
                                    if start_ms is not None:
                                        node_timings["generator"]["first_token_after_start_ms"] = ttft_ms - start_ms
                                logger.warning(f"[TTFT] First token at {ttft_ms}ms for session {request_body.session_id}")
                                try:
                                    add_message(request_body.session_id, "user", request_body.message)
                                    user_message_logged = True
                                except Exception as e:
                                    logger.warning(f"[STREAM] Failed to log user message: {e}")
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
            retrieval_metrics = final_state.values.get("retrieval_metrics", {})
            auto_session_title = None
            if not full_response:
                final_messages = final_state.values.get("messages", [])
                final_message = final_messages[-1] if final_messages else None
                final_content = final_message.content if isinstance(final_message, AIMessage) else ""
                if final_content:
                    import json
                    full_response = final_content
                    if not ttft_logged and ttft_start:
                        ttft_logged = True
                        ttft_ms = int((time.monotonic() - ttft_start) * 1000)
                        generator_first_token_ms = ttft_ms
                        if "generator" in node_timings:
                            start_ms = node_timings["generator"].get("start_ms")
                            if start_ms is not None:
                                node_timings["generator"]["first_token_after_start_ms"] = ttft_ms - start_ms
                        logger.warning(f"[TTFT] First token at {ttft_ms}ms for session {request_body.session_id}")
                        if not user_message_logged:
                            try:
                                add_message(request_body.session_id, "user", request_body.message)
                                user_message_logged = True
                            except Exception as e:
                                logger.warning(f"[STREAM] Failed to log user message: {e}")
                    yield f"event: token\ndata: {json.dumps(final_content)}\n\n"
            try:
                from backend.state.history import get_session, update_session_title, concise_title_from_exchange
                session = get_session(request_body.session_id)
                if session and int(session.get("auto_title_eligible") or 0) == 1 and full_response.strip():
                    proposed_title = concise_title_from_exchange(request_body.message, full_response)
                    if proposed_title != "New Chat":
                        auto_session_title = proposed_title
                        update_session_title(request_body.session_id, auto_session_title, user_id=user.user_id)
                        logger.info(f"[STREAM] Auto-titled session {request_body.session_id}: {auto_session_title}")
            except Exception as e:
                logger.warning(f"[STREAM] Failed to auto-title session: {e}")
            
            # Pass documents exactly as retrieved
            deduped_docs = final_docs

            import json
            ttft_ms = int((time.monotonic() - ttft_start) * 1000) if ttft_start else 0
            timings = {
                "ttft_ms": generator_first_token_ms or ttft_ms,
                "total_backend_ms": ttft_ms,
                "generator_start_ms": generator_start_ms,
                "generator_first_token_ms": generator_first_token_ms,
                "nodes": node_timings,
            }
            retriever_end_ms = node_timings.get("retriever", {}).get("end_ms")
            if isinstance(generator_start_ms, int) and isinstance(retriever_end_ms, int):
                timings["post_retrieval_to_generator_ms"] = max(0, generator_start_ms - retriever_end_ms)
            metadata = json.dumps({
                "intent": final_intent, 
                "sources": deduped_docs,
                "targeted_docs": targeted_docs,
                "ttft_ms": timings["ttft_ms"],
                "timings": timings,
                "retrieval_metrics": retrieval_metrics,
                "session_title": auto_session_title,
            })
            yield f"event: end\ndata: {metadata}\n\n"

            # Log Bot Response
            add_message(
                request_body.session_id, 
                "bot", 
                full_response, 
                final_intent, 
                deduped_docs, 
                metadata={"targeted_docs": targeted_docs, "ttft_ms": ttft_ms},
                thoughts=thoughts
            )

            # Persist summary to sessions table
            summary = final_state.values.get("summary", "")
            if summary:
                try:
                    from backend.state.history import get_connection
                    conn = get_connection()
                    conn.execute("UPDATE sessions SET summary = ? WHERE session_id = ?", (summary, request_body.session_id))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"[STREAM] Failed to persist summary: {e}")
        
        except Exception as e:
            logger.error(f"[STREAM] Error in sse_generator: {e}")
            yield f"event: error\ndata: {str(e)}\n\n"
        finally:
            request_scope.__exit__(None, None, None)

    return StreamingResponse(
        sse_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    session_id: Optional[str] = None
    auto_title_eligible: bool = False

class UpdateSessionTitleRequest(BaseModel):
    title: str

@router.post("/sessions")
def create_session_endpoint(request: CreateSessionRequest, user: SAMLUser = Depends(get_current_user)):
    """Create a new chat session."""
    from backend.state.history import create_new_session
    return create_new_session(
        request.title,
        user_id=user.user_id,
        session_id=request.session_id,
        auto_title_eligible=request.auto_title_eligible,
    )

@router.patch("/sessions/{session_id}/title")
def update_session_title_endpoint(session_id: str, request: UpdateSessionTitleRequest, user: SAMLUser = Depends(get_current_user)):
    """Update a session title."""
    from backend.state.history import update_session_title
    try:
        return update_session_title(session_id, request.title, user_id=user.user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

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
    
    # Security Check: Ensure user owns this session (skip in anonymous mode)
    from backend.config import get_config
    owner = get_session_owner(session_id)
    if get_config().use_saml_login and owner and owner != user.user_id:
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
            "retrieval_detail_top_k": cfg.retrieval_detail_top_k,
            "retrieval_deep_top_k": cfg.retrieval_deep_top_k,
            "ingest_force_cpu": cfg.ingest_force_cpu,
            "ingest_llm_normalize": cfg.ingest_llm_normalize,
            "vlm_model": cfg.vlm_model,
            "parsing_mode": cfg.parsing_mode,
            "model_context_window": cfg.model_context_window,
            "is_thinking_model": cfg.is_thinking_model,
            "no_thinking": cfg.no_thinking,
            "num_predict": cfg.num_predict,
            "temperature": cfg.temperature
        }
    except Exception as e:
        return {"error": f"Config error: {str(e)}"}


async def _run_warmup_task(mode: str, filename: str | None, source: str) -> None:
    try:
        # Compile the graph before the first user stream without touching any
        # session history or checkpointer thread.
        get_graph()
        from backend.llm.warmup import run_warmup
        result = await run_warmup(mode=mode, filename=filename, source=source)
        logger.info("[WARMUP] %s", result)
    except Exception as e:
        logger.info("[WARMUP] Background warmup skipped/failed: %s", e)


@router.post("/warmup")
async def warmup_endpoint(
    background_tasks: BackgroundTasks,
    mode: str = "all",
    filename: Optional[str] = None,
    session_id: Optional[str] = None,
    _user: SAMLUser = Depends(get_current_user),
):
    """Start a best-effort warmup without blocking the caller."""
    normalized_mode = (mode or "all").lower()
    if normalized_mode not in {"all", "chat", "rag", "doc"}:
        normalized_mode = "all"
    background_tasks.add_task(_run_warmup_task, normalized_mode, filename, f"api:{session_id or 'global'}")
    return {"status": "accepted", "mode": normalized_mode, "filename": filename}


@router.get("/warmup")
async def warmup_get_endpoint(
    background_tasks: BackgroundTasks,
    mode: str = "all",
    filename: Optional[str] = None,
    session_id: Optional[str] = None,
    _user: SAMLUser = Depends(get_current_user),
):
    """GET alias for browser/proxy-friendly fire-and-forget warmups."""
    return await warmup_endpoint(background_tasks, mode, filename, session_id, _user)

@router.get("/status")
async def status():
    """
    Cached real-time health check for model query readiness.
    """
    try:
        from backend.llm.health import get_model_health
        snapshot = await get_model_health(force=False)
        snapshot["python_version"] = __import__("sys").version.split()[0]
        return snapshot
    except Exception as e:
        return {
            "status": "offline",
            "python_version": __import__("sys").version.split()[0],
            "chat_available": False,
            "rag_available": False,
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
        raise HTTPException(status_code=404, detail="Document not found")
        
    return FileResponse(found_path)

@router.get("/documents")
def get_documents():
    """List all unique filenames indexed in the vector store."""
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    return {"documents": store.get_all_files()}


