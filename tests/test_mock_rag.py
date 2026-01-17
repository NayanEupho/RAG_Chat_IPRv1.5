import pytest
import logging
import os
from unittest.mock import MagicMock, patch, AsyncMock
from backend.graph.state import AgentState
from backend.config import AppConfig

# Mock logger to avoid errors if nodes use it
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Test Configuration Loading
def test_config_defaults():
    config = AppConfig()
    # It should default to "fused" now
    assert config.rag_workflow == "fused"

# 2. Test Planner Logic (Fast Paths & Mock LLM)
@pytest.mark.asyncio
async def test_planner_fast_path_chat():
    from backend.graph.nodes.planner import planner_node
    
    # State with "Hello" -> Expect Fast Path Chat
    state = {"messages": [MagicMock(content="Hello there")], "mode": "auto"}
    
    result = await planner_node(state)
    assert result["intent"] == "chat"
    assert "query" in result

@pytest.mark.asyncio
async def test_planner_forced_mode():
    from backend.graph.nodes.planner import planner_node
    
    # State with forced "chat" mode
    state = {"messages": [MagicMock(content="Search for documents")], "mode": "chat"}
    
    result = await planner_node(state)
    assert result["intent"] == "chat"

# 3. Test Planner Mock LLM Response (Main Logic)
@pytest.mark.asyncio
async def test_planner_llm_flow():
    with patch("backend.llm.client.OllamaClientWrapper.get_chat_model") as mock_get_client:
        # Mock the LLM Response
        mock_client = AsyncMock()
        mock_client.ainvoke.return_value = MagicMock(content='{"intent": "rag", "rewritten_query": "better query", "semantic_queries": [{"query": "q1", "target": null}]}')
        mock_get_client.return_value = mock_client
        
        from backend.graph.nodes.planner import planner_node
        state = {"messages": [MagicMock(content="Find policies about PTO")], "mode": "auto"}
        
        result = await planner_node(state)
        
        # Verify it parsed the JSON correctly
        assert result["intent"] == "direct_rag" # Mapped from "rag"
        assert result["query"] == "better query"
        assert len(result["semantic_queries"]) == 1
        assert result["semantic_queries"][0]["query"] == "q1"

# 4. Test Graph Structure (Fused Mode)
def test_graph_structure_fused():
    # Use environment variable validation which is natively supported by our AppConfig logic
    # We must patch os.environ AND ensure a fresh config is loaded.
    with patch.dict(os.environ, {"RAG_WORKFLOW": "fused"}):
        # We need to ensure that when `AppConfig()` is instantiated inside build_graph, 
        # it picks up this env var. Pydantic BaseSettings does this automatically.
        # But our AppConfig is a BaseModel, not BaseSettings.
        # Wait, let's look at config.py:
        # `rag_workflow: str = "fused"` -> Default is fused.
        # It DOES NOT inherit from BaseSettings, so it won't read env vars automatically 
        # unless we explicitly code it to (which we did in `get_config` but NOT in the class definition).
        
        # SOLUTION: We must patch the class where it is DEFINED, so that when it is imported
        # inside the function, it uses the mock.
        with patch("backend.config.AppConfig") as MockConfig:
             mock_instance = MockConfig.return_value
             mock_instance.rag_workflow = "fused"
             
             from backend.graph.workflow import build_graph
             app = build_graph()
             assert app is not None

# 5. Test Graph Structure (Modular Mode)
def test_graph_structure_modular():
    # Same strategy: patch the AppConfig class where it is DEFINED.
    with patch("backend.config.AppConfig") as MockConfig:
        mock_instance = MockConfig.return_value
        mock_instance.rag_workflow = "modular"
        
        from backend.graph.workflow import build_graph
        app = build_graph()
        assert app is not None
