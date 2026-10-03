from langgraph.graph import StateGraph, START, END

from jobfit.state import AgentState
from jobfit.nodes import (
    fetch_readmes_node,
    format_bullets_node,
    generate_cv_content_node,
    intake_profile_node,
    match_profile_node,
    parse_jd_node,
    recommend_gaps_node,
    revise_cv_node,
    route_after_cv,
    route_after_match,
)


def build_profile_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intake_profile", intake_profile_node)
    graph.add_node("fetch_readmes", fetch_readmes_node)
    graph.add_node("format_bullets", format_bullets_node)
    graph.add_edge(START, "intake_profile")
    graph.add_edge("intake_profile", "fetch_readmes")
    graph.add_edge("fetch_readmes", "format_bullets")
    graph.add_edge("format_bullets", END)
    return graph.compile()


def build_application_graph():
    graph = StateGraph(AgentState)
    graph.add_node("parse_jd", parse_jd_node)
    graph.add_node("match_profile", match_profile_node)
    graph.add_node("generate_cv_content", generate_cv_content_node)
    graph.add_node("recommend_gaps", recommend_gaps_node)
    graph.add_node("revise_cv", revise_cv_node)
    graph.add_edge(START, "parse_jd")
    graph.add_edge("parse_jd", "match_profile")
    # Optional branch: the user picks a tailored CV or recommendations for their gaps.
    graph.add_conditional_edges("match_profile", route_after_match, ["generate_cv_content", "recommend_gaps"])
    # A revision note edits the CV passed in from an earlier run; generation then skips itself.
    graph.add_conditional_edges("generate_cv_content", route_after_cv, ["revise_cv", END])
    graph.add_edge("revise_cv", END)
    graph.add_edge("recommend_gaps", END)
    return graph.compile()
