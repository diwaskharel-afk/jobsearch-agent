"""The History page: the jobs saved with Save on the Job application page, to open again (no LLM
call), rename, download, delete, or import from a JSON file."""
import json
from datetime import datetime
from typing import Callable

import streamlit as st

from jobfit import history
from jobfit.ui.common import md, safe_filename
from jobfit.ui.job_run import check_run, default_name, has_unsaved_changes, open_saved, saved_entry


def render_history_page(open_job_page: Callable[[], None]) -> None:
    """open_job_page switches to the Job application page once an entry is open."""
    st.title("History")
    st.caption("Jobs you saved with **Save** on the Job application page. Opening one brings back its job fit, "
               "CV, cover letter and suggestions as they were saved, with no AI call.")
    render_import()
    entries = history.list_entries()
    if not entries:
        st.info("Nothing saved yet. Analyse a job on the **Job application** page and click **Save**.")
        return
    unsaved = has_unsaved_changes()
    for entry_id, run in entries:
        render_entry(entry_id, run, unsaved, open_job_page)


def render_import() -> None:
    with st.expander("Import a saved job (JSON)", icon=":material/upload:"):
        with st.form("history_import", border=False, clear_on_submit=True):
            upload = st.file_uploader("Saved job", type="json", label_visibility="collapsed")
            submitted = st.form_submit_button("Import", icon=":material/upload:")
        if not submitted:
            return
        if upload is None:
            st.warning("Choose a file first.")
            return
        try:
            run = json.loads(upload.getvalue())
            parts = check_run(run)
        except Exception as exc:
            st.error("This file can't be opened as a saved job:")
            st.code(str(exc))
            return
        run["name"] = run.get("name") or default_name(parts["jd"].model_dump())
        history.save(f"{datetime.now():%Y%m%d_%H%M%S}_{safe_filename(parts['jd'].title, 'imported')}", run)
        st.success(f"Imported **{md(run['name'])}**.")


def saved_at(run: dict) -> str:
    try:
        return f"{datetime.fromisoformat(run['saved_at']):%d.%m.%Y %H:%M}"
    except (KeyError, TypeError, ValueError):
        return "date unknown"


def render_entry(entry_id: str, run: dict | None, unsaved: bool, open_job_page: Callable[[], None]) -> None:
    is_open = (saved_entry() or {}).get("id") == entry_id
    with st.container(border=True):
        info_col, actions_col = st.columns([3, 2], vertical_alignment="center")
        with info_col:
            if run is None:
                st.markdown(f"**{md(entry_id)}**")
                st.caption(":red[This file can't be read.]")
            else:
                jd = run.get("structured_jd") or {}
                st.markdown(f"**{md(run.get('name') or default_name(jd))}**")
                badges = [f":gray-badge[:material/schedule: {saved_at(run)}]"]
                if jd.get("company"):
                    badges.append(f":blue-badge[:material/apartment: {md(jd['company'])}]")
                badges += [f":green-badge[{label}]" for key, label in
                           (("final_cv", "CV"), ("cover_letter", "Cover letter"), ("gap_plan", "Suggestions"))
                           if run.get(key)]
                if is_open:
                    badges.append(":violet-badge[:material/visibility: Open now]")
                st.markdown(" ".join(badges))
        with actions_col, st.container(horizontal=True, horizontal_alignment="right"):
            if run is not None:
                if st.button("Open", type="primary", icon=":material/open_in_new:", key=f"open_{entry_id}"):
                    if is_open and not unsaved:
                        open_job_page()
                    elif unsaved:
                        confirm_open(entry_id, run, open_job_page)
                    else:
                        open_entry(entry_id, run, open_job_page)
                st.download_button("", icon=":material/download:", key=f"download_{entry_id}", on_click="ignore",
                                   data=json.dumps(run, indent=2, ensure_ascii=False), file_name=f"{entry_id}.json",
                                   mime="application/json", help="Download as JSON")
            render_entry_menu(entry_id, run)


def open_entry(entry_id: str, run: dict, open_job_page: Callable[[], None]) -> None:
    try:
        open_saved(run, entry_id)
    except Exception as exc:
        st.error("This saved job can't be opened:")
        st.code(str(exc))
        return
    open_job_page()


@st.dialog("Unsaved changes")
def confirm_open(entry_id: str, run: dict, open_job_page: Callable[[], None]) -> None:
    st.write("The job you have open has changes that aren't saved. Opening this one replaces it, and those "
             "changes are lost.")
    with st.container(horizontal=True):
        if st.button("Open anyway", type="primary"):
            open_entry(entry_id, run, open_job_page)
        if st.button("Cancel"):
            st.rerun()


def rename(entry_id: str, run: dict) -> None:
    name = st.session_state[f"rename_{entry_id}"].strip()
    if not name:
        return
    history.save(entry_id, {**run, "name": name})
    if (entry := saved_entry()) and entry["id"] == entry_id:
        entry["name"] = name


def delete(entry_id: str) -> None:
    history.delete(entry_id)
    if (entry := saved_entry()) and entry["id"] == entry_id:
        st.session_state["history"] = None  # the open job stays, now unsaved


def render_entry_menu(entry_id: str, run: dict | None) -> None:
    with st.popover("", icon=":material/more_vert:", key=f"menu_{entry_id}"):
        if run is not None:
            st.text_input("Name", value=run.get("name") or default_name(run.get("structured_jd") or {}),
                          key=f"rename_{entry_id}", max_chars=120)
            st.button("Rename", icon=":material/edit:", key=f"rename_go_{entry_id}", on_click=rename,
                      args=(entry_id, run))
            st.divider()
        st.button("Delete", icon=":material/delete:", key=f"delete_{entry_id}", on_click=delete, args=(entry_id,),
                  help="Deletes this saved job for good. A job you have open stays open.")
