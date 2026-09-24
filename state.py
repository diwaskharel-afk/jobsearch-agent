from typing import TypedDict

from model import FinalCV, GapAnalysis, StructuredJD, StructuredProfile


class AgentState(TypedDict, total=False):
    student_profile_input: dict            # raw form payload from Streamlit
    structured_profile: StructuredProfile  # validated output of the intake node
    jd_input: str                          # raw pasted job description
    structured_jd: StructuredJD            # LLM-extracted job description
    gap_analysis: GapAnalysis              # profile-vs-JD comparison
    final_cv: FinalCV                      # tailored CV content, ready to render
