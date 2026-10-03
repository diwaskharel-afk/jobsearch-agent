"""The Job Description tab: run the job graph, then show the match, gap plan, CV and run snapshot."""
import hashlib
import json
import textwrap
from datetime import datetime

import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.llm import TASK_MODELS, model_for
from jobfit.models import FinalCV, GapPlan, JobMatch, StructuredJD, StructuredProfile
from jobfit.render_cv import render_cv_pdf
from jobfit.ui.common import md, safe_filename
from jobfit.ui.cv_revisions import (
    REVISION_KEYS,
    REVISION_PLACEHOLDER,
    editable_cv_preview,
    render_revision_result,
    revise_cv,
    undo_revision,
)
from jobfit.ui.job_results import render_gap_plan, render_job_match


def render_job_tab(existing: StructuredProfile | None) -> None:
    if existing is None:
        st.info("Save your profile in the Profile tab first.")
    else:
        st.caption("Paste a job description, then get a tailored CV or recommendations for the gaps.")
        with st.form("jd_form"):
            jd_text = st.text_area("Paste the job description")
            cv_col, gaps_col = st.columns(2)
            cv_submitted = cv_col.form_submit_button("Tailor CV")
            gaps_submitted = gaps_col.form_submit_button("Recommend for gaps")

        if cv_submitted or gaps_submitted:
            mode = "cv" if cv_submitted else "recommend"
            if not jd_text.strip():
                st.warning("Paste a job description first.")
            else:
                try:
                    inputs = {"jd_input": jd_text, "structured_profile": existing, "mode": mode}
                    # Same JD and profile as last run: reuse the parsed JD and match instead of re-running them.
                    match_key = hashlib.sha256((jd_text.strip() + existing.model_dump_json()).encode()).hexdigest()
                    if st.session_state.get("match_key") == match_key:
                        inputs["structured_jd"] = StructuredJD.model_validate(st.session_state["parsed_jd"])
                        inputs["job_match"] = JobMatch.model_validate(st.session_state["job_match"])
                    else:
                        for key in ("final_cv", "cv_pdf_bytes", "gap_plan", *REVISION_KEYS):
                            st.session_state.pop(key, None)

                    result = build_application_graph().invoke(inputs)
                    st.session_state["match_key"] = match_key
                    st.session_state["jd_input"] = jd_text
                    st.session_state["run_profile"] = existing.model_dump()
                    st.session_state["parsed_jd"] = result["structured_jd"].model_dump()
                    st.session_state["job_match"] = result["job_match"].model_dump()
                    if mode == "cv":
                        st.session_state["final_cv"] = result["final_cv"].model_dump()
                        for key in ("cv_pdf_bytes", *REVISION_KEYS):  # a fresh CV starts again at version 1
                            st.session_state.pop(key, None)
                        st.success("CV tailored.")
                    else:
                        st.session_state["gap_plan"] = result["gap_plan"].model_dump()
                        st.success("Gap recommendations ready.")
                except Exception as exc:
                    st.error("Something went wrong processing this job description:")
                    st.code(str(exc))

        if st.session_state.get("job_match"):
            render_job_match(JobMatch.model_validate(st.session_state["job_match"]))

        if st.session_state.get("gap_plan"):
            render_gap_plan(GapPlan.model_validate(st.session_state["gap_plan"]))

        if st.session_state.get("final_cv"):
            history = st.session_state.setdefault("cv_history", [])
            last_revision = st.session_state.get("last_revision")
            st.subheader("Generated CV")
            version = f"Version {len(history) + 1}"
            if history and last_revision and last_revision["applied"]:
                version += f' · after "{md(textwrap.shorten(last_revision["request"], 70, placeholder="…"))}"'
            st.caption(f"{version}. Preview of the content and layout; the PDF has the final styling.")
            if editable_cv_preview(len(history)):
                st.rerun()  # draw the preview again with the edited CV
            editing = st.session_state.get("cv_editing", False)  # the AI and Undo wait until the edit is saved
            if last_revision:
                render_revision_result(last_revision)

            with st.form("revise_form", clear_on_submit=True):
                revision_request = st.text_area("What should change?", placeholder=REVISION_PLACEHOLDER,
                                                help="Edits the objective, skills and the bullets and tech "
                                                     "stacks of the items already on this CV.")
                revise_submitted = st.form_submit_button("Apply changes", disabled=editing)
            st.button("↩ Undo last change", on_click=undo_revision, disabled=not history or editing)

            if revise_submitted:
                if not revision_request.strip():
                    st.warning("Write what should change first.")
                else:
                    try:
                        with st.spinner("Revising your CV..."):
                            revise_cv(revision_request.strip())
                    except Exception as exc:
                        st.error("Something went wrong revising this CV:")
                        st.code(str(exc))
                    else:
                        st.rerun()  # the preview is drawn above the form, so draw it again with the new CV

            if st.button("Generate PDF"):
                final_cv = FinalCV.model_validate(st.session_state["final_cv"])
                st.session_state["cv_pdf_bytes"] = render_cv_pdf(final_cv)

            if st.session_state.get("cv_pdf_bytes"):
                safe_name = safe_filename((st.session_state["final_cv"].get("name") or "").strip(), "cv")
                st.download_button(
                    "Download CV (PDF)",
                    data=st.session_state["cv_pdf_bytes"],
                    file_name=f"{safe_name}_cv.pdf",
                    mime="application/pdf",
                )

        if st.session_state.get("job_match"):
            run = {
                "saved_at": datetime.now().isoformat(timespec="seconds"),
                "models": {task: model_for(task) for task in TASK_MODELS},
                "jd_input": st.session_state.get("jd_input"),
                "structured_profile": st.session_state.get("run_profile"),
                "structured_jd": st.session_state["parsed_jd"],
                "job_match": st.session_state["job_match"],
                "gap_plan": st.session_state.get("gap_plan"),
                "final_cv": st.session_state.get("final_cv"),
                "revisions": st.session_state.get("revisions"),
            }
            run_filename = (f"{datetime.now():%Y%m%d_%H%M%S}_"
                            f"{safe_filename(st.session_state['parsed_jd'].get('title'), 'run')}.json")
            with st.expander("Raw data & download"):
                st.caption("Snapshot of the JD, profile, match and any generated CV / gap plan, "
                           "for analysing output quality. Nothing is saved to disk.")
                st.download_button(
                    "Download run (JSON)",
                    data=json.dumps(run, indent=2, ensure_ascii=False),
                    file_name=run_filename,
                    mime="application/json",
                )
                raw_sections = [
                    ("Parsed job description", run["structured_jd"]),
                    ("Job match", run["job_match"]),
                    ("Gap plan", run["gap_plan"]),
                    ("Generated CV (latest version)", run["final_cv"]),
                    ("CV revisions", run["revisions"]),
                    ("Profile used for this run", run["structured_profile"]),
                    ("Models used", run["models"]),
                ]
                for label, data in raw_sections:
                    if data:
                        with st.expander(label):
                            st.json(data)
