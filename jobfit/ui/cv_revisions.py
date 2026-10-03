"""CV versions: AI revisions, hand edits and Undo."""
import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.models import FinalCV, JobMatch, StructuredJD, StructuredProfile
from jobfit.nodes import apply_revision
from jobfit.ui.common import md
from jobfit.ui.cv_preview import render_cv_preview

REVISION_KEYS = ("cv_history", "last_revision", "revisions", "cv_editing")  # reset whenever a new CV is generated
REVISION_PLACEHOLDER = ("e.g. Don't call me junior in the profile. Add my Docker sandbox work to the analyst "
                        "project. Remove Excel from skills.")

# A note from the user edits the current CV (one AI call), or the user edits the text by hand
# (no AI call). Each change that actually alters the CV becomes a new version; the older ones
# are kept in cv_history for Undo.


def revise_cv(request: str) -> None:
    old = st.session_state["final_cv"]
    inputs = {  # this run's snapshot, so profile edits made since can't mix into this CV
        "structured_profile": StructuredProfile.model_validate(st.session_state["run_profile"]),
        "structured_jd": StructuredJD.model_validate(st.session_state["parsed_jd"]),
        "job_match": JobMatch.model_validate(st.session_state["job_match"]),
        "final_cv": FinalCV.model_validate(old),
        "mode": "cv",
        "revision_request": request,
    }
    result = build_application_graph().invoke(inputs)
    new, revision = result["final_cv"].model_dump(), result["cv_revision"]
    save_version(new, request, revision.changes, revision.not_done)


def save_version(new: dict, request: str, changes: list[str], not_done: list[str]) -> None:
    """Make `new` the current CV, keeping the old one for Undo. An unchanged CV makes no new version."""
    old = st.session_state["final_cv"]
    applied = new != old
    if applied:
        st.session_state["cv_history"].append(old)
        st.session_state["final_cv"] = new
        st.session_state.pop("cv_pdf_bytes", None)
    last = {"request": request, "applied": applied, "changes": changes if applied else [], "not_done": not_done}
    st.session_state["last_revision"] = last
    st.session_state.setdefault("revisions", []).append(last)


def stop_editing() -> None:
    st.session_state["cv_editing"] = False


def editable_cv_preview(version: int) -> bool:
    """The CV preview with an Edit button that turns its text into boxes in place (no AI call).
    Saving applies them with the same code as an AI revision. True once saved, so the caller can redraw."""
    cv = FinalCV.model_validate(st.session_state["final_cv"])
    if not st.session_state.get("cv_editing"):
        st.button("✏️ Edit", on_click=lambda: st.session_state.update(cv_editing=True))
        render_cv_preview(cv)
        return False
    with st.form(f"cv_edit_{version}"):
        revision = render_cv_preview(cv, edit=True, version=version)
        save_col, cancel_col, _ = st.columns([1, 1, 4])
        saved = save_col.form_submit_button("Save", type="primary")
        cancel_col.form_submit_button("Cancel", on_click=stop_editing)
    if not saved:
        return False
    stop_editing()
    save_version(apply_revision(cv, revision).model_dump(), "Manual edit", ["Edited by hand"], [])
    return True


def undo_revision() -> None:
    st.session_state["final_cv"] = st.session_state["cv_history"].pop()
    st.session_state.pop("cv_pdf_bytes", None)
    st.session_state.pop("last_revision", None)
    st.session_state.setdefault("revisions", []).append({"undo": True})


def render_revision_result(last: dict) -> None:
    if not last["applied"]:
        st.info("No changes were made to the CV.")
    elif last["changes"]:
        st.success("**Changed:**\n" + "\n".join(f"- {md(c)}" for c in last["changes"]))
    else:
        st.success("CV updated.")
    if last["not_done"]:
        st.warning("**Not done:**\n" + "\n".join(f"- {md(n)}" for n in last["not_done"]))
