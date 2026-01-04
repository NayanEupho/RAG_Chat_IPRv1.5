from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from backend.graph.workflow import build_graph
from langchain_core.messages import HumanMessage, AIMessage
import uuid

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
async def chat_endpoint(request: ChatRequest):
    """
    Classic chat endpoint (Non-Streaming).
    """
    try:
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
async def chat_stream_endpoint(request: ChatRequest):
    """
    Streaming chat endpoint with History Logging.
    """
    from backend.state.history import add_message, create_session
    
    # Ensure session exists
    create_session(request.session_id)
    
    # Log User Message Immediately
    add_message(request.session_id, "user", request.message)

    config = {"configurable": {"thread_id": request.session_id}}
    inputs = {
        "messages": [HumanMessage(content=request.message)],
        "mode": request.mode
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
               event_type = event["event"]
               # print(f"DEBUG: Event: {event_type}") # Removed as per instruction snippet
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
                   # Filter: Only yield tokens from the actual Answer Generator
                   # This prevents the Router's internal classification (JSON) from leaking.
                   meta = event.get("metadata", {})
                   node = meta.get("langgraph_node", "")
                   
                   if node == "generator":
                       chunk = event["data"]["chunk"]
                       if hasattr(chunk, 'content') and chunk.content:
                           import json
                           clean_token = json.dumps(chunk.content)
                           full_response += chunk.content
                           yield f"event: token\ndata: {clean_token}\n\n"

           # End of Stream, fetch final state
           final_state = await get_graph().aget_state(config)
           final_intent = final_state.values.get("intent", "unknown")
           final_docs = final_state.values.get("documents", [])
           targeted_docs = final_state.values.get("targeted_docs", [])
           
           # Deduplicate Sources while preserving content
           # The frontend expects "Source: {name}\nContent: {text}"
           # We group chunks by filename so the UI shows one button per file.
           unique_sources = {}
           for doc in final_docs:
                if "Source: " in doc and "\nContent: " in doc:
                    parts = doc.split("\nContent: ", 1)
                    src_name = parts[0].replace("Source: ", "").strip()
                    content = parts[1]
                    
                    if src_name not in unique_sources:
                        unique_sources[src_name] = []
                    unique_sources[src_name].append(content)
           
           deduped_docs = []
           for src, contents in unique_sources.items():
               combined_content = "\n\n---\n\n".join(contents)
               deduped_docs.append(f"Source: {src}\nContent: {combined_content}")

           import json
           metadata = json.dumps({
               "intent": final_intent, 
               "sources": deduped_docs,
               "targeted_docs": targeted_docs
           })
           yield f"event: end\ndata: {metadata}\n\n"

           # Log Bot Response with Metadata AND Thoughts
           add_message(
               request.session_id, 
               "bot", 
               full_response, 
               final_intent, 
               deduped_docs, # Save deduped docs as sources
               metadata={"targeted_docs": targeted_docs},
               thoughts=thoughts
           )
        
        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(sse_generator(), media_type="text/event-stream")

class CreateSessionRequest(BaseModel):
    title: Optional[str] = None

@router.post("/sessions")
def create_session_endpoint(request: CreateSessionRequest):
    """Create a new chat session."""
    from backend.state.history import create_new_session
    return create_new_session(request.title)

@router.get("/sessions")
def get_sessions():
    """List all available chat sessions with metadata."""
    from backend.state.history import get_all_sessions
    return {"sessions": get_all_sessions()}

@router.delete("/sessions/{session_id}")
def delete_session_endpoint(session_id: str):
    """Delete a session permenantly."""
    from backend.state.history import delete_session
    try:
        delete_session(session_id)
        return {"status": "deleted", "id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history/{session_id}")
def get_history(session_id: str):
    """Get full message history for a session."""
    from backend.state.history import get_session_history
    return {"messages": get_session_history(session_id)}

@router.get("/config")
def get_config_route():
    """Get current application configuration."""
    from backend.config import get_config
    try:
        cfg = get_config()
        return {
            "main_model": cfg.main_model.model_name if cfg.main_model else None,
            "main_host": cfg.main_model.host if cfg.main_model else None,
            "embed_model": cfg.embedding_model.model_name if cfg.embedding_model else None,
            "embed_host": cfg.embedding_model.host if cfg.embedding_model else None,
        }
    except Exception as e:
        return {"error": f"Config error: {str(e)}"}

@router.get("/status")
def status():
    return {"status": "ok", "graph": "compiled"}

@router.get("/documents")
def get_documents():
    """List all unique filenames indexed in the vector store."""
    from backend.rag.store import get_vector_store
    store = get_vector_store()
    return {"documents": store.get_all_files()}
