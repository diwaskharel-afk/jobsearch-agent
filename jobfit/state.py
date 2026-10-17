from typing import Literal, TypedDict

from jobfit.models import (
    CoverLetter,
    CoverLetterRevision,
    CVRevision,
    FinalCV,
    GapPlan,
    JobMatch,
    StructuredJD,
    StructuredProfile,
)


class AgentState(TypedDict, total=False):
    student_profile_input: dict            # raw form payload from Streamlit
    structured_profile: StructuredProfile  # validated output of the intake node, with ids
    previous_profile: StructuredProfile    # last saved profile; its READMEs and bullets are reused by entry id
    refresh_readme_ids: list[str]          # projects whose README is re-read even though the link is unchanged
    profile_warnings: list[str]            # shown after saving: unreadable repos, projects left without bullets
    profile_actions: list[str]             # shown after saving: READMEs read and bullets written by this save
    jd_input: str                          # raw pasted job description
    structured_jd: StructuredJD            # LLM-extracted job description
    job_match: JobMatch                    # ranked items, relevant skills, missing requirements
    final_cv: FinalCV                      # tailored CV content, ready to render
    revision_request: str                  # the user's note for changing final_cv; empty = no revision
    cv_revision: CVRevision                # what the revision changed or refused, for the UI
    # Which branch to take after matching; "analyse" stops after the match.
    mode: Literal["analyse", "cv", "recommend", "cover_letter"]
    gap_plan: GapPlan                      # suggestions for closing the missing requirements
    cover_letter: CoverLetter              # cover letter for this job, ready to render
    letter_revision_request: str           # the user's note for changing cover_letter; empty = no revision
    letter_revision: CoverLetterRevision   # what the letter revision changed or refused, for the UI
