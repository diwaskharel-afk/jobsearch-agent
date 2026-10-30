from langgraph.graph import StateGraph, START, END

from jobfit.state import AgentState
from jobfit.nodes import (
    fetch_readmes_node,
    format_bullets_node,
    generate_cover_letter_node,
    generate_cv_content_node,
    intake_profile_node,
    match_profile_node,
    parse_jd_node,
    recommend_gaps_node,
    revise_cover_letter_node,
    revise_cv_node,
    route_after_cv,
    route_after_letter,
    route_after_match,
    swap_cv_item_node,
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
    graph.add_node("swap_cv_item", swap_cv_item_node)
    graph.add_node("generate_cover_letter", generate_cover_letter_node)
    graph.add_node("revise_cover_letter", revise_cover_letter_node)
    graph.add_edge(START, "parse_jd")
    graph.add_edge("parse_jd", "match_profile")
    # Optional branch: stop after the match ("analyse"), or write a tailored CV, a cover letter
    # or recommendations for the gaps.
    graph.add_conditional_edges("match_profile", route_after_match,
                                [END, "generate_cv_content", "generate_cover_letter", "recommend_gaps"])
    # A revision note (or, for the CV, a swap) edits the CV or letter passed in from an earlier run;
    # generation then skips itself.
    graph.add_conditional_edges("generate_cv_content", route_after_cv, ["revise_cv", "swap_cv_item", END])
    graph.add_conditional_edges("generate_cover_letter", route_after_letter, ["revise_cover_letter", END])
    graph.add_edge("revise_cv", END)
    graph.add_edge("swap_cv_item", END)
    graph.add_edge("revise_cover_letter", END)
    graph.add_edge("recommend_gaps", END)
    return graph.compile()
