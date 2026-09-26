from typing import Literal, TypedDict

from model import FinalCV, GapPlan, JobMatch, StructuredJD, StructuredProfile


class AgentState(TypedDict, total=False):
    student_profile_input: dict            # raw form payload from Streamlit
    structured_profile: StructuredProfile  # validated output of the intake node, with ids
    jd_input: str                          # raw pasted job description
    structured_jd: StructuredJD            # LLM-extracted job description
    job_match: JobMatch                    # ranked items, relevant skills, missing requirements
    final_cv: FinalCV                      # tailored CV content, ready to render
    mode: Literal["cv", "recommend"]       # which branch to take after matching
    gap_plan: GapPlan                      # suggestions for closing the missing requirements
