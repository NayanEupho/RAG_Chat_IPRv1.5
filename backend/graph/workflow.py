from langgraph.graph import StateGraph, END
from backend.graph.state import AgentState
from backend.graph.nodes.router import route_query
from backend.graph.nodes.rewriter import rewrite_query
from backend.graph.nodes.retriever import retrieve_documents
from backend.graph.nodes.generate import generate_answer
from backend.state.checkpoint import get_checkpointer

def build_graph():
    workflow = StateGraph(AgentState)
    
    # Add Nodes
    workflow.add_node("router", route_query)
    workflow.add_node("rewriter", rewrite_query)
    workflow.add_node("retriever", retrieve_documents)
    workflow.add_node("generator", generate_answer)
    
    # Define Edges
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
    workflow.add_edge("retriever", "generator")
    workflow.add_edge("generator", END)
    
    # Compile
    checkpointer = get_checkpointer()
    app = workflow.compile(checkpointer=checkpointer)
    return app
