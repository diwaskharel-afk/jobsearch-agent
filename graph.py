from langgraph.graph import StateGraph, START, END

from state import AgentState
from nodes import (
    format_bullets_node,
    gap_analysis_node,
    generate_cv_content_node,
    intake_profile_node,
    parse_jd_node,
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
    graph.add_node("gap_analysis", gap_analysis_node)
    graph.add_node("generate_cv_content", generate_cv_content_node)
    graph.add_edge(START, "parse_jd")
    graph.add_edge("parse_jd", "gap_analysis")
    graph.add_edge("gap_analysis", "generate_cv_content")
    graph.add_edge("generate_cv_content", END)
    return graph.compile()
