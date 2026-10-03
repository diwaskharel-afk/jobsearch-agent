"""JobFit: run with `streamlit run app.py` from the repo root."""
import streamlit as st

from jobfit import storage
from jobfit.ui.job_tab import render_job_tab
from jobfit.ui.profile_tab import render_profile_tab

st.set_page_config(page_title="JobFit", page_icon="\U0001F4DD")
st.title("JobFit")

existing = storage.load_profile()

profile_tab, jd_tab = st.tabs(["Profile", "Job Description"])

with profile_tab:
    render_profile_tab(existing)

with jd_tab:
    render_job_tab(existing)
