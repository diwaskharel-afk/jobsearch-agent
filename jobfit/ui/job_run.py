"""The job being worked on: its analysis (parsed JD + match), the inputs every later step reuses,
and the run snapshot for the download."""
import hashlib
from datetime import datetime

import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.llm import TASK_MODELS, model_for
from jobfit.models import FinalCV, JobMatch, StructuredJD, StructuredProfile
from jobfit.nodes import cv_item_ids, pick_for_cv, pick_for_letter
from jobfit.ui import versions

JOB_KEYS = ("match_key", "jd_input", "run_profile", "parsed_jd", "job_match", "gap_plan")
DOCS = ("cv", "letter")  # documents written for the job, each with its own versions


def has_job() -> bool:
    return bool(st.session_state.get("job_match"))


def clear_job() -> None:
    for key in JOB_KEYS:
        st.session_state.pop(key, None)
    for doc in DOCS:
        versions.reset(doc)


def analyse_job(jd_text: str, profile: StructuredProfile) -> None:
    """Parse the JD and match it with the profile. A new job or profile starts the workspace over;
    the same JD and profile keep the current analysis and everything written for it."""
    match_key = hashlib.sha256((jd_text.strip() + profile.model_dump_json()).encode()).hexdigest()
    if st.session_state.get("match_key") == match_key:
        return
    result = build_application_graph().invoke({"jd_input": jd_text, "structured_profile": profile, "mode": "analyse"})
    clear_job()
    st.session_state.update(
        match_key=match_key,
        jd_input=jd_text,
        run_profile=profile.model_dump(),  # this run's snapshot, so later profile edits can't mix into it
        parsed_jd=result["structured_jd"].model_dump(),
        job_match=result["job_match"].model_dump(),
    )


def rerun_match() -> None:
    """A fresh match for the same job and profile (the parsed JD is reused). The CV, letter and
    plan already written stay as they are; generating them again uses the new ranking."""
    inputs = run_inputs("analyse")
    del inputs["job_match"]
    st.session_state["job_match"] = build_application_graph().invoke(inputs)["job_match"].model_dump()


def picks() -> dict[str, list[str]]:
    """Ids of the items each document is written from: the CV's own items once it's written (swaps
    change them), otherwise those picked from the current ranking."""
    match = JobMatch.model_validate(st.session_state["job_match"])
    cv = versions.current("cv")
    return {"cv": cv_item_ids(FinalCV.model_validate(cv)) if cv else pick_for_cv(match),
            "letter": pick_for_letter(match)}


def run_inputs(mode: str, **extra) -> dict:
    """Graph inputs for one step of this job; parsing and matching are skipped, as they're passed in."""
    return {
        "structured_profile": StructuredProfile.model_validate(st.session_state["run_profile"]),
        "structured_jd": StructuredJD.model_validate(st.session_state["parsed_jd"]),
        "job_match": JobMatch.model_validate(st.session_state["job_match"]),
        "mode": mode,
        **extra,
    }


def run_snapshot() -> dict:
    """The JD, profile, match and everything written for it, for analysing output quality."""
    return {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "models": {task: model_for(task) for task in TASK_MODELS},
        "jd_input": st.session_state.get("jd_input"),
        "structured_profile": st.session_state.get("run_profile"),
        "structured_jd": st.session_state.get("parsed_jd"),
        "job_match": st.session_state.get("job_match"),
        "picks": picks() if has_job() else None,
        "gap_plan": st.session_state.get("gap_plan"),
        "final_cv": versions.current("cv"),
        "revisions": versions.log("cv"),
        "cover_letter": versions.current("letter"),
        "letter_revisions": versions.log("letter"),
    }
