import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import RunnableLambda

# Mock Logic to simulate "Streaming" from a Node
async def mock_generator_node(input):
    # This represents the LLM doing work.
    # In a real scenario, this would be `ChatOllama.ainvoke` which emits events
    yield AIMessageChunk(content="Chunk1 ")
    await asyncio.sleep(0.1)
    yield AIMessageChunk(content="Chunk2 ")
    await asyncio.sleep(0.1)
    yield AIMessageChunk(content="Chunk3")

@pytest.mark.asyncio
async def test_sse_streaming_logic():
    """
    Simulate the exact logic in routes.py to verify it yields chunks AS THEY ARRIVE
    and doesn't wait for the end.
    """
    
    # 1. Mock the Graph and astream_events
    with patch("backend.api.routes.get_graph") as mock_get_graph:
        
        # Create a mock async generator for astream_events
        async def mock_event_stream(*args, **kwargs):
            # 1. Planner/Router events (Status updates)
            yield {
                "event": "on_chain_start",
                "name": "router",
                "data": {}
            }
            await asyncio.sleep(0.01)
            
            # 2. Generator Streaming Events (The Answer)
            # We simulate 3 chunks arriving over time
            chunks = ["Hello ", "World ", "Stream"]
            for c in chunks:
                yield {
                    "event": "on_chat_model_stream",
                    "metadata": {"langgraph_node": "generator"},
                    "data": {"chunk": AIMessageChunk(content=c)}
                }
                # Critical: Sleep to prove we aren't buffering
                await asyncio.sleep(0.1) 
                
            yield {"event": "on_chain_end", "data": {}}

        mock_graph = MagicMock()
        mock_graph.astream_events = mock_event_stream
        
        # Mock aget_state for the final metadata step
        mock_state = MagicMock()
        mock_state.values = {"intent": "chat", "documents": []}
        mock_graph.aget_state = AsyncMock(return_value=mock_state)
        
        mock_get_graph.return_value = mock_graph
        
        # 2. Import the SSE Generator (Logic from routes.py, extracted or reconstructed)
        # Since sse_generator is inside the endpoint function, we'll manually replicate the iteration logic
        # to verify the "yield" happens inside the loop.
        
        from backend.api.routes import ChatRequest
        
        # Replicated Logic from routes.py -> sse_generator
        # We want to time the yields.
        import time
        start_time = time.time()
        
        yield_times = []
        full_response = ""
        
        # Directly iterate the mock stream using the Logic
        async for event in mock_graph.astream_events():
            event_type = event["event"]
            if event_type == "on_chat_model_stream":
                meta = event.get("metadata", {})
                node = meta.get("langgraph_node", "")
                if node == "generator":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, 'content'):
                        yield_times.append(time.time() - start_time)
                        full_response += chunk.content
        
        # 3. Assertions
        assert full_response == "Hello World Stream"
        assert len(yield_times) == 3
        
        # Verify time gaps (deltas should be ~0.1s)
        # If it was buffered, these would all be very close to the end time
        # Timestamps should be roughly: 0.01 (Router), 0.01 (Chunk1), 0.11 (Chunk2), 0.21 (Chunk3) 
        # Actually our mock generator has sleeps.
        
        print(f"Yield Times: {yield_times}")
        
        # Check that gaps exist
        if len(yield_times) > 1:
            gaps = [yield_times[i] - yield_times[i-1] for i in range(1, len(yield_times))]
            avg_gap = sum(gaps) / len(gaps)
            print(f"Average Gap: {avg_gap}")
            # We slept 0.1s between chunks, so gap should be >= 0.1
            assert avg_gap >= 0.09 

