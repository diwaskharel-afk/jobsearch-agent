"""Show the CV preview of a saved run log in the browser, without running the pipeline.

    streamlit run tools/preview_cv.py                                  # pick a run in the sidebar
    streamlit run tools/preview_cv.py -- TestRunJson/20261001_143244_AI_Solution_Architect.json

Dev tool: lists the run logs in TestRunJson/ and the project folder (or takes an uploaded
one), and draws its final_cv with the same render_cv_preview the app uses, plus the PDF.
"""
import sys
import tempfile
from pathlib import Path

import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent.parent  # the repo root
sys.path.insert(0, str(PROJECT_DIR))  # so `jobfit` imports when this file is run directly

from jobfit.models import FinalCV
from jobfit.render_cv import render_cv_pdf
from jobfit.ui.common import safe_filename
from jobfit.ui.cv_preview import render_cv_preview
from render_run_pdf import load_final_cv

RUN_DIRS = (PROJECT_DIR / "TestRunJson", PROJECT_DIR)


def saved_runs() -> list[Path]:
    runs = [run for folder in RUN_DIRS if folder.is_dir() for run in folder.glob("[0-9]*_*.json")]
    return sorted(runs, key=lambda run: run.name, reverse=True)


def load_uploaded(upload) -> FinalCV:
    """Same checks (and old-log fix-up) as a run on disk, via a temp copy outside the project."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / upload.name
        path.write_bytes(upload.getvalue())
        return load_final_cv(path)


st.set_page_config(page_title="CV preview test", page_icon="\U0001F4C4")
st.title("CV preview test")

runs = saved_runs()
cli_run = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if cli_run and cli_run not in runs:
    runs.insert(0, cli_run)

with st.sidebar:
    st.header("Run log")
    upload = st.file_uploader("Upload a run (JSON)", type="json")
    run_path = st.selectbox(
        "…or pick a saved run", runs, index=runs.index(cli_run) if cli_run else 0,
        format_func=lambda run: run.name if run.parent in RUN_DIRS else str(run), disabled=upload is not None,
    ) if runs else None

if upload is None and run_path is None:
    st.info("No saved runs in TestRunJson/ or the project folder; upload one in the sidebar.")
    st.stop()

try:
    cv = load_uploaded(upload) if upload is not None else load_final_cv(run_path)
except SystemExit as exc:  # load_final_cv exits on a run without a final_cv
    st.error(str(exc))
    st.stop()
except Exception as exc:
    st.error("This run's final_cv couldn't be read:")
    st.code(str(exc))
    st.stop()

st.caption(f"Run: {upload.name if upload is not None else run_path.name}  ·  "
           f"{len(cv.skills)} skills, {len(cv.experience)} experience, {len(cv.projects)} projects, "
           f"{len(cv.education)} education, {len(cv.courses)} courses")

st.subheader("Generated CV")
render_cv_preview(cv)

st.download_button(
    "Download CV (PDF)",
    data=render_cv_pdf(cv),
    file_name=f"{safe_filename(cv.name, 'cv')}_cv.pdf",
    mime="application/pdf",
)
with st.expander("final_cv (JSON)"):
    st.json(cv.model_dump())
