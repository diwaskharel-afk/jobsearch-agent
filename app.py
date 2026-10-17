"""JobFit: run with `streamlit run app.py` from the repo root."""
import streamlit as st

from jobfit import storage
from jobfit.ui.job_page import render_job_page
from jobfit.ui.profile_tab import render_profile_tab

st.set_page_config(page_title="JobFit", page_icon=":material/work:", layout="wide")

existing = storage.load_profile()


def profile_page() -> None:
    st.title("Your profile")
    render_profile_tab(existing)


def job_page() -> None:
    render_job_page(existing)


page = st.navigation([
    st.Page(profile_page, title="Profile", icon=":material/person:", url_path="profile", default=existing is None),
    st.Page(job_page, title="Job application", icon=":material/work:", url_path="job", default=existing is not None),
])

with st.sidebar:
    if existing is not None:
        st.caption(f"**{existing.name or 'Your profile'}**  \n"
                   f"Projects {len(existing.projects)} · Experience {len(existing.experience)} · "
                   f"Education {len(existing.education)} · Courses {len(existing.courses)}")
    if jd := st.session_state.get("parsed_jd"):
        st.caption(f"**Current job:** {jd.get('title')}" + (f" at {jd['company']}" if jd.get("company") else ""))
    st.toggle("Developer mode", key="dev_mode", help="Show the raw data of a job run and its JSON download.")

page.run()
