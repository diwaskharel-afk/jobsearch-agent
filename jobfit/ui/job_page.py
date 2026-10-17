"""The Job application page: paste a job, analyse it once, then work on each part in its own tab."""
import json
from datetime import datetime

import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.models import GapPlan, JobMatch, StructuredJD, StructuredProfile
from jobfit.ui.common import empty_state, md, run_step, safe_filename
from jobfit.ui.cv_view import render_cv_section
from jobfit.ui.job_results import render_gap_plan, render_job_match
from jobfit.ui.job_run import analyse_job, has_job, picks, rerun_match, run_inputs, run_snapshot
from jobfit.ui.letter_view import render_letter_section

FIT, CV, LETTER, PLAN = (":material/insights: Job fit", ":material/description: CV",
                         ":material/mail: Cover letter", ":material/lightbulb: Suggestions")


def render_job_page(existing: StructuredProfile | None) -> None:
    st.title("Job application")
    if existing is None:
        st.info("Fill in and save your profile first: open **Profile** in the sidebar.")
        return
    if not has_job() or st.session_state.get("changing_job"):
        render_jd_form(existing)
        return

    render_job_header(existing)
    fit_tab, cv_tab, letter_tab, plan_tab = st.tabs([FIT, CV, LETTER, PLAN], key="job_section", on_change="rerun")
    # Only the open tab runs, so a click inside one never redraws (or resets) the others.
    if fit_tab.open:
        with fit_tab:
            render_fit_section()
    if cv_tab.open:
        with cv_tab:
            render_cv_section()
    if letter_tab.open:
        with letter_tab:
            render_letter_section()
    if plan_tab.open:
        with plan_tab:
            render_plan_section()

    if st.session_state.get("dev_mode"):
        render_run_data()


def render_jd_form(existing: StructuredProfile) -> None:
    changing = has_job()
    st.caption("Paste a job posting. It's compared with your profile once; then you can write a tailored CV "
               "and a cover letter for it, and get suggestions (projects and courses) for the skills it asks "
               "for that you don't show yet.")
    with st.form("jd_form"):
        jd_text = st.text_area("Job description", value=st.session_state.get("jd_input", ""), height=300,
                               placeholder="Paste the whole job posting here...")
        with st.container(horizontal=True):
            submitted = st.form_submit_button("Analyse job", type="primary", icon=":material/search:")
            if changing:
                st.form_submit_button("Cancel", on_click=lambda: st.session_state.pop("changing_job", None))
    if changing:
        st.caption("Analysing a different job starts over: its CV and cover letter replace the current ones.")
    if not submitted:
        return
    if not jd_text.strip():
        st.warning("Paste a job description first.")
    elif run_step("Reading the job and comparing it with your profile...", lambda: analyse_job(jd_text, existing),
                  "Something went wrong processing this job description:"):
        st.session_state.pop("changing_job", None)
        st.rerun()


def render_job_header(existing: StructuredProfile) -> None:
    jd = StructuredJD.model_validate(st.session_state["parsed_jd"])
    with st.container(border=True):
        title_col, actions_col = st.columns([4, 1], vertical_alignment="center")
        with title_col:
            st.markdown(f"### {md(jd.title)}", anchors=False)
            badges = []
            if jd.company:
                badges.append(f":blue-badge[:material/apartment: {md(jd.company)}]")
            if jd.seniority:
                badges.append(f":violet-badge[{md(jd.seniority)}]")
            if badges:
                st.markdown(" ".join(badges))
        actions_col.button("Change job", icon=":material/swap_horiz:", width="stretch",
                           on_click=lambda: st.session_state.update(changing_job=True))

    if existing.model_dump() != st.session_state["run_profile"]:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.warning("Your profile has changed since this job was analysed. Analyse it again to use the "
                       "new profile (this starts the CV and cover letter over).", width="stretch")
            if st.button("Analyse again", icon=":material/refresh:"):
                if run_step("Comparing the job with your updated profile...",
                            lambda: analyse_job(st.session_state["jd_input"], existing),
                            "Something went wrong processing this job description:"):
                    st.rerun()


def render_fit_section() -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("The ranking decides what goes into your CV and cover letter.", width="stretch")
        if st.button("Re-run match", icon=":material/refresh:",
                     help="Ask for a fresh ranking of this job. What you've already written stays; "
                          "generate it again to use the new ranking."):
            if run_step("Matching your profile with the job again...", rerun_match,
                        "Something went wrong matching the profile:"):
                st.rerun()
    render_job_match(JobMatch.model_validate(st.session_state["job_match"]),
                     StructuredJD.model_validate(st.session_state["parsed_jd"]), picks())


def build_gap_plan() -> None:
    st.session_state["gap_plan"] = build_application_graph().invoke(run_inputs("recommend"))["gap_plan"].model_dump()


def render_plan_section() -> None:
    if not st.session_state.get("gap_plan"):
        if empty_state("Suggestions", "Ways to show what this job asks for that your profile doesn't yet: "
                       "improve one of your projects, build a small new one, or take a course or certification "
                       "(found with a web search, low-cost first).", "Get suggestions", ":material/lightbulb:",
                       key="plan_generate"):
            if run_step("Finding suggestions and searching for courses...", build_gap_plan,
                        "Something went wrong finding suggestions:"):
                st.rerun()
        return
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("#### Suggestions", width="stretch")
        if st.button("Refresh", icon=":material/refresh:", help="Ask for new suggestions; these are replaced."):
            if run_step("Finding new suggestions and searching for courses...", build_gap_plan,
                        "Something went wrong finding suggestions:"):
                st.rerun()
    render_gap_plan(GapPlan.model_validate(st.session_state["gap_plan"]),
                    has_gaps=bool(JobMatch.model_validate(st.session_state["job_match"]).missing))


def render_run_data() -> None:
    run = run_snapshot()
    run_filename = f"{datetime.now():%Y%m%d_%H%M%S}_{safe_filename(run['structured_jd'].get('title'), 'run')}.json"
    st.divider()
    with st.expander("Developer: raw data and run download", icon=":material/code:"):
        st.caption("Snapshot of the JD, profile, match and everything written for this job, for analysing "
                   "output quality. Nothing is saved to disk.")
        st.download_button("Download run (JSON)", data=json.dumps(run, indent=2, ensure_ascii=False),
                           file_name=run_filename, mime="application/json", on_click="ignore")
        raw_sections = [
            ("Parsed job description", run["structured_jd"]),
            ("Job match", run["job_match"]),
            ("Items picked for the CV and letter", run["picks"]),
            ("Suggestions", run["gap_plan"]),
            ("CV (current version)", run["final_cv"]),
            ("CV revisions", run["revisions"]),
            ("Cover letter (current version)", run["cover_letter"]),
            ("Cover letter revisions", run["letter_revisions"]),
            ("Profile used for this run", run["structured_profile"]),
            ("Models used", run["models"]),
        ]
        for label, data in raw_sections:
            if data:
                with st.expander(label):
                    st.json(data)
