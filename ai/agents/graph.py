"""
Agent Graph module.

Defines the LangGraph StateGraph that orchestrates all compliance agents.
The five analysis agents run sequentially, followed by the decision agent
that synthesises the final compliance output.
"""

from langgraph.graph import END, StateGraph

from ai.agents.decision_agent import decision_agent
from ai.agents.document_agent import document_agent
from ai.agents.rag_agent import rag_agent
from ai.agents.sanctions_agent import sanctions_agent
from ai.agents.temporal_agent import temporal_agent
from ai.agents.transaction_agent import transaction_agent
from ai.core.schemas import AgentState

# ---------------------------------------------------------------------------
# Build the compliance StateGraph
# ---------------------------------------------------------------------------
graph = StateGraph(AgentState)

# --- Register nodes --------------------------------------------------------
graph.add_node("document_agent", document_agent)
graph.add_node("rag_agent", rag_agent)
graph.add_node("transaction_agent", transaction_agent)
graph.add_node("sanctions_agent", sanctions_agent)
graph.add_node("temporal_agent", temporal_agent)
graph.add_node("decision_agent", decision_agent)

# --- Define execution order ------------------------------------------------
# All five analysis agents run sequentially, then feed into the decision agent.
graph.set_entry_point("document_agent")

graph.add_edge("document_agent", "rag_agent")
graph.add_edge("rag_agent", "transaction_agent")
graph.add_edge("transaction_agent", "sanctions_agent")
graph.add_edge("sanctions_agent", "temporal_agent")
graph.add_edge("temporal_agent", "decision_agent")
graph.add_edge("decision_agent", END)

# --- Compile ---------------------------------------------------------------
compliance_graph = graph.compile()


# ---------------------------------------------------------------------------
# Graph execution function
# ---------------------------------------------------------------------------
async def run_graph(initial_state: AgentState) -> AgentState:
    """
    Execute the compliance graph with the given initial state.
    
    Args:
        initial_state: The initial AgentState to process.
        
    Returns:
        The final AgentState after graph execution.
    """
    # LangGraph's invoke returns the final state
    final_state = await compliance_graph.ainvoke(initial_state)
    return final_state
