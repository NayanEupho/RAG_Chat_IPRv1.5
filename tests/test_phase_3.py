import os
import sys
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.graph.state import AgentState
from backend.graph.nodes.router import route_query
from backend.graph.nodes.generate import generate_answer
from langchain_core.messages import HumanMessage

@pytest.mark.asyncio
async def test_router_regex():
    """Test Intent Detection Regex."""
    # State Mock
    state = {
        "messages": [HumanMessage(content="Give me a summary of @report.pdf")], 
        "query": "", "intent": ""
    }
    
    result = await route_query(state)
    assert result['intent'] == "specific_doc_rag"
    assert result['specific_file'] == "report.pdf"
    assert "summary" in result['query']

@pytest.mark.asyncio
async def test_router_heuristic():
    """Test Intent Detection Heuristic."""
    state = {
        "messages": [HumanMessage(content="What is the capital of France?")], 
        "query": "", "intent": ""
    }
    # Current heuristic defaults to direct_rag for simplicity in code
    result = await route_query(state)
    assert result['intent'] == "direct_rag"

if __name__ == "__main__":
    # Simple async runner
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(test_router_regex())
        loop.run_until_complete(test_router_heuristic())
        print("Phase 3: Router Logic Tests PASSED")
    except AssertionError as e:
        print(f"Phase 3: Router Tests FAILED: {e}")
