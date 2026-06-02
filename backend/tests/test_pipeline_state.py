from langgraph.graph import START, StateGraph

from specforge.pipeline.state import PipelineState


def test_current_node_accepts_multiple_updates_in_one_step():
    builder = StateGraph(PipelineState)
    builder.add_node("finished_prd", lambda state: {"status": "planning", "current_node": None})
    builder.add_node("started_test_plan", lambda state: {"status": "planning", "current_node": "test_planner"})
    builder.add_edge(START, "finished_prd")
    builder.add_edge(START, "started_test_plan")

    graph = builder.compile()

    result = graph.invoke({"iteration_id": "iteration-1", "status": "queued", "current_node": "prd_planner"})

    assert result["status"] == "planning"
    assert result["current_node"] == "test_planner"
