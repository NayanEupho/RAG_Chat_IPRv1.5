from langgraph.graph import StateGraph, END
from backend.graph.state import AgentState
from backend.graph.nodes.router import route_query
from backend.graph.nodes.rewriter import rewrite_query
from backend.graph.nodes.retriever import retrieve_documents
from backend.graph.nodes.generate import generate_answer
from backend.state.checkpoint import get_checkpointer
import logging

logger = logging.getLogger(__name__)

def build_graph():
    workflow = StateGraph(AgentState)
    
    # Define Edges
    
    # DYNAMIC WORKFLOW SWITCH
    from backend.config import AppConfig
    config = AppConfig()
    
    # MODE 1: FUSED (One-Shot Planner)
    # Optimized for Speed (Low Latency). Requires 72B+ Model.
    if config.rag_workflow == "fused":
        logger.info("[WORKFLOW] Mode: FUSED (Planner -> Retriever)")
        
        # Add Planner Node
        from backend.graph.nodes.planner import planner_node
        workflow.add_node("planner", planner_node)
        workflow.set_entry_point("planner")
        
        # Internal Routing Logic
        # The Planner decides intent internally. We just route based on that decision.
        def planner_route(state):
            if state['intent'] == 'chat':
                return "generator"
            else:
                return "retriever"
        
        workflow.add_conditional_edges(
            "planner",
            planner_route,
            {
                "generator": "generator",
                "retriever": "retriever"
            }
        )
        
    # MODE 2: MODULAR (Sequential Chain)
    # Optimized for Stability. Good for 7B/14B Models.
    else:
        logger.info("[WORKFLOW] Mode: MODULAR (Router -> Rewriter -> Retriever)")
        
        # Add Nodes
        workflow.add_node("router", route_query)
        workflow.add_node("rewriter", rewrite_query)
        
        workflow.set_entry_point("router")
    
        # Conditional Edge from Router
        def route_decision(state):
            if state['intent'] == 'chat':
                return "generator"
            else:
                return "rewriter"
                
        workflow.add_conditional_edges(
            "router",
            route_decision,
            {
                "generator": "generator",
                "rewriter": "rewriter"
            }
        )
        
        workflow.add_edge("rewriter", "retriever")

    # Common Edges (Shared by both modes)
    workflow.add_node("retriever", retrieve_documents)
    workflow.add_node("generator", generate_answer)
    workflow.add_edge("retriever", "generator")
    workflow.add_edge("generator", END)
    
    # Compile
    checkpointer = get_checkpointer()
    app = workflow.compile(checkpointer=checkpointer)
    return app
