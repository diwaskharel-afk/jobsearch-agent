"""The Job application page: paste a job, analyse it once, then work on each part in its own tab."""
import streamlit as st

from jobfit.graph import build_application_graph
from jobfit.models import GapPlan, JobMatch, StructuredJD, StructuredProfile
from jobfit.ui.common import empty_state, md, run_step
from jobfit.ui.cv_view import render_cv_section
from jobfit.ui.job_results import render_gap_plan, render_job_match
from jobfit.ui.job_run import (analyse_job, default_name, has_job, has_unsaved_changes, picks, rerun_match,
                               run_inputs, save_job, saved_entry)
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
            render_save_status()
        with actions_col:
            render_save_menu(jd)
            st.button("Change job", icon=":material/swap_horiz:", width="stretch",
                      on_click=lambda: st.session_state.update(changing_job=True),
                      help="Unsaved work on this job is lost; save it first to keep it.")

    if existing.model_dump() != st.session_state["run_profile"]:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.warning("Your profile has changed since this job was analysed. Analyse it again to use the "
                       "new profile (this starts the CV and cover letter over).", width="stretch")
            if st.button("Analyse again", icon=":material/refresh:"):
                if run_step("Comparing the job with your updated profile...",
                            lambda: analyse_job(st.session_state["jd_input"], existing),
                            "Something went wrong processing this job description:"):
                    st.rerun()


def render_save_status() -> None:
    entry = saved_entry()
    if entry is None:
        st.caption(":material/bookmark_border: Not saved. **Save** keeps it in History.")
    elif has_unsaved_changes():
        st.caption(f":material/bookmark: Saved as **{md(entry['name'])}** · :orange[unsaved changes]")
    else:
        st.caption(f":material/bookmark: Saved as **{md(entry['name'])}**")


def render_save_menu(jd: StructuredJD) -> None:
    """Save the job to History under a name: over its entry once it has one, or as a new entry."""
    entry = saved_entry()
    form_key = f"save_job_{entry['id'] if entry else st.session_state['match_key']}"  # refills the name per entry
    with st.popover("Save", icon=":material/bookmark:", width="stretch"):
        with st.form(form_key, border=False):
            name = st.text_input("Name", value=entry["name"] if entry else default_name(jd.model_dump()),
                                 max_chars=120)
            as_new = st.checkbox("Save as a new entry", help="Keeps the saved one as it is.") if entry else False
            submitted = st.form_submit_button("Save", type="primary", icon=":material/check:")
        st.caption("Saves the job fit, CV, cover letter and suggestions as they are now. Open it again from "
                   "**History**; no AI needed.")
    if submitted:
        save_job(name.strip() or default_name(jd.model_dump()), as_new)
        st.rerun()  # redraw the status line above


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
                    JobMatch.model_validate(st.session_state["job_match"]))
