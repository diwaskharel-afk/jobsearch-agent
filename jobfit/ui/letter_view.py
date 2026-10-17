"""The cover letter section of a job: write it, preview it, change it by hand or with AI, Undo/Redo, download."""
from datetime import date

import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.models import CoverLetter, StructuredProfile
from jobfit.nodes import letter_date, unpicked_mentions
from jobfit.render_letter import letter_text, render_letter_pdf
from jobfit.ui import versions
from jobfit.ui.common import empty_state, md, run_step, safe_filename
from jobfit.ui.letter_preview import apply_letter_edits, render_letter_preview
from jobfit.ui.job_run import run_inputs

DOC = "letter"
REVISION_PLACEHOLDER = ("e.g. Make the opening less formal. Talk more about my RAG project. "
                        "Make it a bit shorter.")
REVISION_HELP = "Rewrites the body of the letter. The date, greeting and sign-off can be changed with Edit."


def generate_letter() -> None:
    """A fresh letter for this job: the first version, or a new one on top of the current."""
    letter = build_application_graph().invoke(run_inputs("cover_letter"))["cover_letter"].model_dump()
    if versions.has(DOC):
        versions.add_version(DOC, letter, "Rewritten", ["Wrote a fresh letter for this job"], [])
    else:
        versions.start(DOC, letter, "Written")


def revise_letter(request: str) -> None:
    """One AI call that edits the current letter; the result becomes a new version."""
    inputs = run_inputs("cover_letter", cover_letter=CoverLetter.model_validate(versions.current(DOC)),
                        letter_revision_request=request)
    result = build_application_graph().invoke(inputs)
    revision = result["letter_revision"]
    versions.add_version(DOC, result["cover_letter"].model_dump(), request, revision.changes, revision.not_done)


@st.cache_data(max_entries=32, show_spinner=False)
def letter_pdf(letter_json: str) -> bytes:
    return render_letter_pdf(CoverLetter.model_validate_json(letter_json))


def _render(data: dict, edit: bool, version: int):
    return render_letter_preview(CoverLetter.model_validate(data), edit=edit, version=version)


def _apply(data: dict, edits: dict) -> dict:
    return apply_letter_edits(CoverLetter.model_validate(data), edits).model_dump()


def render_letter_section() -> None:
    if not versions.has(DOC):
        text = ("A short, personal letter about why this kind of work interests you, told through what "
                "you've actually built and done. It's written from the items ranked high or medium for this "
                "job in Job fit, and nothing else.")
        if empty_state("Cover letter", text, "Write my cover letter", ":material/mail:", key="letter_generate"):
            if run_step("Writing your cover letter...", generate_letter,
                        "Something went wrong writing the cover letter:"):
                st.rerun()
        return

    letter = CoverLetter.model_validate(versions.current(DOC))
    name = safe_filename((letter.name or "").strip(), "cover_letter")
    downloads = [
        {"label": "Download PDF", "icon": ":material/download:", "data": letter_pdf(letter.model_dump_json()),
         "file_name": f"{name}_cover_letter.pdf", "mime": "application/pdf"},
        {"label": "Text", "icon": ":material/notes:", "data": letter_text(letter),
         "file_name": f"{name}_cover_letter.txt", "mime": "text/plain",
         "help": "Plain text, for pasting into an application form."},
    ]
    if versions.toolbar(DOC, downloads, "Writes a fresh letter as a new version; Undo brings this one back."):
        if run_step("Writing a fresh letter...", generate_letter, "Something went wrong writing the cover letter:"):
            st.rerun()

    preview_col, side_col = st.columns([3, 2], gap="large")
    with preview_col:
        if versions.editable_preview(DOC, _render, _apply):
            st.rerun()  # draw the preview again with the edited letter
        if letter.date and letter.date != letter_date(date.today()) and not versions.is_editing(DOC):
            st.info(f"This letter is dated **{md(letter.date)}**. Click **Edit** to change the date before "
                    "you send it.")
        if mentions := unpicked_mentions(letter, StructuredProfile.model_validate(st.session_state["run_profile"])):
            st.warning("The letter mentions " + ", ".join(f"**{md(m)}**" for m in mentions) + ", which wasn't "
                       "ranked relevant to this job, so its details weren't checked against your profile.")
    with side_col:
        versions.revise_panel(DOC, revise_letter, REVISION_PLACEHOLDER, REVISION_HELP, "Revising your letter...")
