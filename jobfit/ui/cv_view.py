"""The CV section of a job: write it, preview it, change it by hand or with AI, swap its items,
Undo/Redo, download."""
import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.models import FinalCV, JobMatch
from jobfit.nodes import apply_revision, swap_candidates
from jobfit.render_cv import render_cv_pdf
from jobfit.ui import versions
from jobfit.ui.common import empty_state, md, run_step, safe_filename
from jobfit.ui.cv_preview import render_cv_preview
from jobfit.ui.job_results import RELEVANCE_LABELS
from jobfit.ui.job_run import run_inputs

DOC = "cv"
REVISION_PLACEHOLDER = ("e.g. Don't call me junior in the profile. Add my Docker sandbox work to the analyst "
                        "project. Remove Excel from skills.")
REVISION_HELP = ("Edits the profile text, skills, and the bullets and tech stacks of the items already on this CV. "
                 "To put a different item on the CV, use the swap button next to it.")
SWAP_PENDING = "cv_swap_pending"  # (old id, new id) picked in a swap menu, run on the next draw


def generate_cv() -> None:
    """A fresh CV for this job: the first version, or a new one on top of the current."""
    cv = build_application_graph().invoke(run_inputs("cv"))["final_cv"].model_dump()
    if versions.has(DOC):
        versions.add_version(DOC, cv, "Regenerated", ["Wrote a fresh CV for this job"], [])
    else:
        versions.start(DOC, cv)


def revise_cv(request: str) -> None:
    """One AI call that edits the current CV; the result becomes a new version."""
    inputs = run_inputs("cv", final_cv=FinalCV.model_validate(versions.current(DOC)), revision_request=request)
    result = build_application_graph().invoke(inputs)
    revision = result["cv_revision"]
    versions.add_version(DOC, result["final_cv"].model_dump(), request, revision.changes, revision.not_done)


def swap_item(old_id: str, new_id: str) -> None:
    """Put new_id on the CV in old_id's place (one AI call, none for a course); the result becomes a new version."""
    inputs = run_inputs("cv", final_cv=FinalCV.model_validate(versions.current(DOC)), swap_out=old_id, swap_in=new_id)
    result = build_application_graph().invoke(inputs)
    swap = result["cv_swap"]
    versions.add_version(DOC, result["final_cv"].model_dump(), swap.changes[0], swap.changes, [])


def request_swap(old_id: str, new_id: str | None) -> None:
    if new_id:
        st.session_state[SWAP_PENDING] = (old_id, new_id)


def take_swap() -> tuple[str, str] | None:
    """The swap picked in a menu since the last draw, if any; it's run outside the menu, so its
    spinner and errors show in place and the menu closes."""
    return st.session_state.pop(SWAP_PENDING, None)


def swap_menu(item_id: str) -> None:
    """A small swap button; it opens the profile items that could take this one's place, best match first."""
    cv = FinalCV.model_validate(versions.current(DOC))
    candidates = swap_candidates(cv, item_id, JobMatch.model_validate(st.session_state["job_match"]))
    index, _ = versions.position(DOC)
    with st.popover("", icon=":material/swap_horiz:", type="tertiary", key=f"swap_menu_{item_id}_{index}",
                    help="Swap this for another item from your profile"):
        if not candidates:
            st.caption("Every item of this kind in your profile is already on the CV.")
            return
        by_id = {c.id: c for c in candidates}
        choice = st.radio("Swap for", list(by_id), key=f"swap_choice_{item_id}_{index}",
                          format_func=lambda i: by_id[i].name,
                          captions=[f"{RELEVANCE_LABELS[c.relevance]} · {md(c.reason)}" for c in candidates])
        note = "Writes bullets for it in this job's language." if not item_id.startswith("course_") else ""
        st.button("Swap", type="primary", icon=":material/swap_horiz:", key=f"swap_go_{item_id}_{index}",
                  help=note or None, on_click=request_swap, args=(item_id, choice))


def run_pending_swap() -> bool:
    """Run a swap picked in a menu, with its spinner here; True if it ran, so the caller redraws."""
    if not (swap := take_swap()):
        return False
    return run_step("Swapping the item and writing it for this job...", lambda: swap_item(*swap),
                    "Something went wrong swapping the item:")


@st.cache_data(max_entries=32, show_spinner=False)
def cv_pdf(cv_json: str) -> bytes:
    return render_cv_pdf(FinalCV.model_validate_json(cv_json))


def _render(data: dict, edit: bool, version: int):
    return render_cv_preview(FinalCV.model_validate(data), edit=edit, version=version,
                             swap_menu=None if edit else swap_menu)


def _apply(data: dict, revision) -> dict:
    return apply_revision(FinalCV.model_validate(data), revision).model_dump()


def editable_cv() -> bool:
    """The CV preview, or its edit boxes after Edit; True once a hand edit is saved."""
    return versions.editable_preview(DOC, _render, _apply)


def render_cv_section() -> None:
    if not versions.has(DOC):
        if empty_state("Tailored CV", "Picks your most relevant projects and experience for this job and "
                       "rewrites their bullets in the job's language. Nothing you haven't done is added.",
                       "Tailor my CV", ":material/description:", key="cv_generate"):
            if run_step("Writing your CV...", generate_cv, "Something went wrong writing the CV:"):
                st.rerun()
        return

    cv = FinalCV.model_validate(versions.current(DOC))
    name = safe_filename((cv.name or "").strip(), "cv")
    downloads = [{"label": "Download PDF", "icon": ":material/download:", "data": cv_pdf(cv.model_dump_json()),
                  "file_name": f"{name}_cv.pdf", "mime": "application/pdf"}]
    if versions.toolbar(DOC, downloads, "Writes a fresh CV for this job as a new version; Undo brings this one back."):
        if run_step("Writing a fresh CV...", generate_cv, "Something went wrong writing the CV:"):
            st.rerun()

    preview_col, side_col = st.columns([3, 2], gap="large")
    with preview_col:
        if run_pending_swap():
            st.rerun()  # draw the toolbar and preview again with the new version
        if editable_cv():
            st.rerun()  # draw the preview again with the edited CV
        st.caption("A preview of the content and layout; the PDF has the final styling.")
    with side_col:
        versions.revise_panel(DOC, revise_cv, REVISION_PLACEHOLDER, REVISION_HELP, "Revising your CV...")
