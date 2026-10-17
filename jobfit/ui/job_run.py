"""The job being worked on: its analysis (parsed JD + match), the inputs every later step reuses,
the run snapshot, and saving it to History and opening it again."""
import hashlib
import json
from datetime import datetime

import streamlit as st

from jobfit import history
from jobfit.graph import build_application_graph
from jobfit.llm import TASK_MODELS, model_for
from jobfit.models import CoverLetter, FinalCV, GapPlan, JobMatch, StructuredJD, StructuredProfile
from jobfit.nodes import cv_item_ids, pick_for_cv, pick_for_letter
from jobfit.ui import versions
from jobfit.ui.common import safe_filename

# "history" is the entry this job was saved as or opened from: {"id", "name", "hash"}. Analysing
# a job clears it with the rest, so the new analysis is saved as a new entry and never overwrites one.
JOB_KEYS = ("match_key", "jd_input", "run_profile", "parsed_jd", "job_match", "gap_plan", "history")
DOCS = ("cv", "letter")  # documents written for the job, each with its own versions
UNSAVED_KEYS = ("saved_at", "models", "name")  # left out when checking for unsaved changes


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
    key = match_key(jd_text, profile)
    if st.session_state.get("match_key") == key:
        return
    result = build_application_graph().invoke({"jd_input": jd_text, "structured_profile": profile, "mode": "analyse"})
    clear_job()
    st.session_state.update(
        match_key=key,
        jd_input=jd_text,
        run_profile=profile.model_dump(),  # this run's snapshot, so later profile edits can't mix into it
        parsed_jd=result["structured_jd"].model_dump(),
        job_match=result["job_match"].model_dump(),
    )


def match_key(jd_text: str, profile: StructuredProfile) -> str:
    return hashlib.sha256((jd_text.strip() + profile.model_dump_json()).encode()).hexdigest()


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


# --- History -----------------------------------------------------------------------------

def default_name(jd: dict) -> str:
    return (jd.get("title") or "Untitled job") + (f" — {jd['company']}" if jd.get("company") else "")


def _content_hash(run: dict) -> str:
    content = {key: value for key, value in run.items() if key not in UNSAVED_KEYS}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def saved_entry() -> dict | None:
    """The History entry this job was saved as or opened from, if any."""
    return st.session_state.get("history")


def has_unsaved_changes() -> bool:
    """True for a job never saved, or changed since it was saved or opened."""
    entry = saved_entry()
    return has_job() and (entry is None or entry["hash"] != _content_hash(run_snapshot()))


def save_job(name: str, as_new: bool = False) -> None:
    """Save the job to History: over the entry it was saved as or opened from, or as a new one."""
    entry = saved_entry()
    if entry is None or as_new:
        entry_id = f"{datetime.now():%Y%m%d_%H%M%S}_{safe_filename(st.session_state['parsed_jd'].get('title'), 'job')}"
    else:
        entry_id = entry["id"]
    run = {"name": name, **run_snapshot()}
    history.save(entry_id, run)
    st.session_state["history"] = {"id": entry_id, "name": name, "hash": _content_hash(run)}


def check_run(run: dict) -> dict:
    """The parts of a saved run, validated, so a file that can't be opened fails before the open
    job is touched. Raises ValueError if it can't be opened."""
    if not isinstance(run, dict) or not all(run.get(key) for key in ("structured_profile", "structured_jd",
                                                                      "job_match")):
        raise ValueError("This isn't a saved job: it has no profile, job description or match.")
    return {
        "profile": StructuredProfile.model_validate(run["structured_profile"]),
        "jd": StructuredJD.model_validate(run["structured_jd"]),
        "match": JobMatch.model_validate(run["job_match"]),
        "gap_plan": GapPlan.model_validate(run["gap_plan"]) if run.get("gap_plan") else None,
        "cv": FinalCV.model_validate(run["final_cv"]) if run.get("final_cv") else None,
        "letter": CoverLetter.model_validate(run["cover_letter"]) if run.get("cover_letter") else None,
    }


def open_saved(run: dict, entry_id: str) -> None:
    """Make a saved entry the open job, as it was saved; no LLM call. It keeps the profile it was
    analysed with. The CV and letter come back as their saved version, without earlier ones."""
    parts = check_run(run)
    jd_text = run.get("jd_input") or ""
    clear_job()
    st.session_state.update(
        match_key=match_key(jd_text, parts["profile"]),
        jd_input=jd_text,
        run_profile=parts["profile"].model_dump(),
        parsed_jd=parts["jd"].model_dump(),
        job_match=parts["match"].model_dump(),
    )
    if parts["gap_plan"]:
        st.session_state["gap_plan"] = parts["gap_plan"].model_dump()
    if parts["cv"]:
        versions.start("cv", parts["cv"].model_dump(), "Saved")
    if parts["letter"]:
        versions.start("letter", parts["letter"].model_dump(), "Saved")
    name = run.get("name") or default_name(st.session_state["parsed_jd"])
    st.session_state["history"] = {"id": entry_id, "name": name, "hash": _content_hash(run_snapshot())}
