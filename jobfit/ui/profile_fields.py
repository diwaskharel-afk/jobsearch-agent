"""The profile form's entry cards and the fields of each kind of entry."""
from uuid import uuid4

import streamlit as st

from jobfit.ui.dates import PAST_YEARS, date_badge, date_range_fields, month_year_picker

EDUCATION_PRESENT = "I'm currently studying here"
EXPERIENCE_PRESENT = "I currently work here"
DATED_SECTIONS = ("education", "experience")  # their cards need a start and an end (or present)


# --- Profile entry cards ------------------------------------------------------------
# Each multi-entry section (projects, courses, ...) is a list of cards kept in session
# state, seeded once from the saved profile. Every card has a uid so its widget keys stay
# stable when another card is removed.

def section_entries(section: str, saved: list) -> list[dict]:
    key = f"entries_{section}"
    if key not in st.session_state:
        st.session_state[key] = [{"uid": uuid4().hex, **item.model_dump()} for item in saved]
    return st.session_state[key]


def add_entry(section: str) -> None:
    st.session_state[f"entries_{section}"].append({"uid": uuid4().hex})


def remove_entry(section: str, uid: str) -> None:
    key = f"entries_{section}"
    st.session_state[key] = [e for e in st.session_state[key] if e["uid"] != uid]


def entry_cards(section: str, noun: str, saved: list, render_fields) -> list[dict]:
    """One bordered card per entry plus an "Add" button below them; returns each card's values.

    render_fields(entry, key) draws a card's inputs and returns its values; key(field) gives
    the card's widget key for that field.
    """
    values = []
    for n, entry in enumerate(section_entries(section, saved), start=1):
        uid = entry["uid"]
        with st.container(border=True):
            title_col, remove_col = st.columns([4, 1], vertical_alignment="center")
            title = title_col.empty()  # filled after the fields, so its date badge follows the pickers
            remove_col.button("🗑 Remove", key=f"{section}_{uid}_remove", on_click=remove_entry, args=(section, uid))
            card = render_fields(entry, lambda field, uid=uid: f"{section}_{uid}_{field}")
            title.markdown(f"**{noun.capitalize()} {n}** &nbsp; {date_badge(card, section in DATED_SECTIONS)}")
            values.append(card)
    st.button(f"➕ Add {noun}", key=f"{section}_add", on_click=add_entry, args=(section,))
    return values


def optional_text_area(label: str, value: str, key: str, toggle_label: str = "Add description") -> str:
    """Text area hidden behind a checkbox; "" while the box is unticked."""
    if st.checkbox(toggle_label, value=bool(value), key=f"{key}_toggle"):
        return st.text_area(label, value=value, key=key)
    return ""



def education_fields(entry: dict, key) -> dict:
    values = {
        "degree": st.text_input("Degree / programme", value=entry.get("degree") or "", key=key("degree")),
        "institution": st.text_input("Institution", value=entry.get("institution") or "", key=key("institution")),
        **date_range_fields(entry, key, EDUCATION_PRESENT, expected_graduation=True),
    }
    values["description"] = optional_text_area("Description", entry.get("description") or "", key("description"))
    return values


def course_fields(entry: dict, key) -> dict:
    return {
        "id": entry.get("id"),
        "name": st.text_input("Course name", value=entry.get("name") or "", key=key("name")),
        "provider": st.text_input("Provider (school or platform)", value=entry.get("provider") or "", key=key("provider")),
        "date": month_year_picker("Completed (optional)", entry.get("date"), key("date"), PAST_YEARS),
        "description": optional_text_area("What it covered", entry.get("description") or "", key("description"),
                                          toggle_label="Add what it covered"),
    }


def project_fields(entry: dict, key) -> dict:
    values = {
        "id": entry.get("id"),
        "repo_url": st.text_input("GitHub link", value=entry.get("repo_url") or "", key=key("repo_url"),
                                  placeholder="https://github.com/you/project",
                                  help="Also shown on the CV. Private repos need a GITHUB_TOKEN in .env."),
        "name": st.text_input("Name", value=entry.get("name") or "", key=key("name"),
                              help="Leave empty to use the repo's name."),
        "description": optional_text_area("Description", entry.get("description") or "", key("description")),
    }
    # Only for a saved link: a new or changed link is always read on save.
    if entry.get("id") and entry.get("readme"):
        values["refresh_readme"] = st.checkbox("🔄 Re-read README from GitHub on save", key=key("refresh_readme"),
                                               help="Tick after pushing README changes to the repo.")
    return values


def experience_fields(entry: dict, key) -> dict:
    title = st.text_input("Title", value=entry.get("title") or "", key=key("title"))
    organization = st.text_input("Organization", value=entry.get("organization") or "", key=key("organization"))
    dates = date_range_fields(entry, key, EXPERIENCE_PRESENT)
    resp_raw = st.text_area("Responsibilities (one per line)", value="\n".join(entry.get("responsibilities") or []),
                            key=key("responsibilities"))
    return {
        "id": entry.get("id"),
        "title": title,
        "organization": organization,
        **dates,
        "responsibilities": [r.strip() for r in resp_raw.splitlines() if r.strip()],
    }


def certification_fields(entry: dict, key) -> dict:
    return {
        "id": entry.get("id"),
        "name": st.text_input("Name", value=entry.get("name") or "", key=key("name")),
        "issuer": st.text_input("Issuer", value=entry.get("issuer") or "", key=key("issuer")),
        "date": month_year_picker("Date (optional)", entry.get("date"), key("date"), PAST_YEARS),
    }


def is_blank(entry: dict) -> bool:
    return not any(value for field, value in entry.items() if field not in ("id", "present"))
