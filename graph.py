from langgraph.graph import StateGraph, START, END

from state import AgentState
from nodes import (
    format_bullets_node,
    generate_cv_content_node,
    intake_profile_node,
    match_profile_node,
    parse_jd_node,
    recommend_gaps_node,
    route_after_match,
)


def build_profile_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intake_profile", intake_profile_node)
    graph.add_node("format_bullets", format_bullets_node)
    graph.add_edge(START, "intake_profile")
    graph.add_edge("intake_profile", "format_bullets")
    graph.add_edge("format_bullets", END)
    return graph.compile()


def build_application_graph():
    graph = StateGraph(AgentState)
    graph.add_node("parse_jd", parse_jd_node)
    graph.add_node("match_profile", match_profile_node)
    graph.add_node("generate_cv_content", generate_cv_content_node)
    graph.add_node("recommend_gaps", recommend_gaps_node)
    graph.add_edge(START, "parse_jd")
    graph.add_edge("parse_jd", "match_profile")
    # Optional branch: the user picks a tailored CV or recommendations for their gaps.
    graph.add_conditional_edges("match_profile", route_after_match, ["generate_cv_content", "recommend_gaps"])
    graph.add_edge("generate_cv_content", END)
    graph.add_edge("recommend_gaps", END)
    return graph.compile()
