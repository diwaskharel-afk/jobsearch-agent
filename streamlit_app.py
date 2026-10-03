import hashlib
import json
import re
import textwrap
from datetime import date, datetime
from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

import storage
from github_repo import parse_github_url
from graph import build_application_graph, build_profile_graph
from llm import TASK_MODELS, model_for
from formatting import format_month
from model import CVRevision, FinalCV, GapPlan, JobMatch, RevisedCVItem, StructuredJD, StructuredProfile
from nodes import apply_revision
from render_cv import MAX_TECH_SHOWN, _clean, _date, _pretty_project_name, render_cv_pdf

RELEVANCE_LABELS = {"high": "🟢 high", "medium": "🟡 medium", "low": "🟠 low", "none": "⚪ none"}
EFFORT_LABELS = {"hours": "⏱ hours", "days": "📅 days", "weeks": "🗓 weeks", "months": "📆 months"}
ITEM_TYPES = {"proj": "project", "exp": "experience", "cert": "certification", "course": "course"}
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PAST_YEARS = list(range(date.today().year, 1969, -1))
FUTURE_YEARS = list(range(date.today().year, date.today().year + 9))
EDUCATION_PRESENT = "I'm currently studying here"
EXPERIENCE_PRESENT = "I currently work here"
DATED_SECTIONS = ("education", "experience")  # their cards need a start and an end (or present)
REVISION_KEYS = ("cv_history", "last_revision", "revisions", "cv_editing")  # reset whenever a new CV is generated
REVISION_PLACEHOLDER = ("e.g. Don't call me junior in the profile. Add my Docker sandbox work to the analyst "
                        "project. Remove Excel from skills.")


def safe_filename(text: str | None, fallback: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (text or "")).strip("_") or fallback


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


# --- Dates ----------------------------------------------------------------------------
# Dates are picked as month + year and stored as "YYYY-MM". A picker with only one of the
# two filled in returns a partial value (e.g. "2024-"), which date_problem reports on save.

def is_full_date(value: str | None) -> bool:
    return value is not None and len(value) == len("YYYY-MM")


def month_year_picker(label: str, value: str | None, key: str, years: list[int], cols=None) -> str | None:
    """A month and a year dropdown side by side, labelled once; "YYYY-MM", a partial value, or None.

    cols is the (month, year) column pair to draw them in; by default the left half of a row.
    """
    year, month = (int(value[:4]), int(value[5:])) if value else (None, None)
    if year is not None and year not in years:
        years = sorted({*years, year}, reverse=years[0] > years[-1])
    month_col, year_col = cols or st.columns(4)[:2]
    month = month_col.selectbox(label, range(1, 13), index=month - 1 if month else None,
                                format_func=lambda m: MONTH_NAMES[m - 1], placeholder="Month", key=f"{key}_month")
    # A short hidden label: a long one still wraps invisibly and pushes the row down.
    year = year_col.selectbox("Year", years, index=years.index(year) if year else None,
                              placeholder="Year", label_visibility="hidden", key=f"{key}_year")
    if month is None and year is None:
        return None
    return f"{year or ''}-{month:02d}" if month else f"{year}-"


def date_range_fields(entry: dict, key, present_label: str, expected_graduation: bool = False) -> dict:
    """A "present" toggle over one row of From and To pickers; end is None while present is on.

    While present is on, the To slot shows "Present", or for education (expected_graduation=True)
    the expected graduation pickers, which are then required.
    """
    present = st.toggle(present_label, value=bool(entry.get("start")) and not entry.get("end"), key=key("present"))
    cols = st.columns(4, vertical_alignment="bottom")
    values = {"start": month_year_picker("From", entry.get("start"), key("start"), PAST_YEARS, cols[:2]),
              "end": None, "present": present}
    if not present:
        values["end"] = month_year_picker("To", entry.get("end"), key("end"), PAST_YEARS, cols[2:])
    elif expected_graduation:
        values["expected_graduation"] = month_year_picker("Expected graduation", entry.get("expected_graduation"),
                                                          key("expected_graduation"), FUTURE_YEARS, cols[2:])
    else:
        cols[2].text_input("To", value="Present", disabled=True, key=key("end_present"))
    return values


def date_badge(card: dict, required: bool) -> str:
    """Card-header badge with the dates as the CV shows them; a warning while required ones are missing."""
    start, end, completed = card.get("start"), card.get("end"), card.get("date")
    if is_full_date(start) and card.get("present"):
        badge = f":green-badge[:material/schedule: {format_month(start)} – Present]"
        if is_full_date(card.get("expected_graduation")):
            badge += f" :violet-badge[:material/school: Graduating {format_month(card['expected_graduation'])}]"
        return badge
    if is_full_date(start) and is_full_date(end):
        return f":blue-badge[:material/calendar_month: {format_month(start)} – {format_month(end)}]"
    if is_full_date(completed):
        return f":blue-badge[:material/calendar_month: {format_month(completed)}]"
    return ":orange-badge[:material/warning: Dates needed]" if required else ""


def date_problem(value: str | None, what: str, required: bool) -> str | None:
    if value is None:
        return f"needs {what}" if required else None
    if not is_full_date(value):
        return f"needs both the month and the year of {what}"
    return None


def range_problems(label: str, entry: dict, present_label: str) -> list[str]:
    """Missing, partial or out-of-order dates of one education or experience card."""
    if entry["present"]:
        later_field, later_name = "expected_graduation", "expected graduation date"
    else:
        later_field, later_name = "end", f"end date (or turn on \"{present_label}\")"
    problems = [date_problem(entry["start"], "a start date", required=True)]
    if later_field in entry:  # experience has no expected graduation
        problems.append(date_problem(entry[later_field], f"an {later_name}", required=True))
    problems = [f"{label} {p}." for p in problems if p]
    later = entry.get(later_field)
    if not problems and later and later < entry["start"]:
        problems.append(f"{label}: the {later_field.replace('_', ' ')} date is before the start date.")
    return problems


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


def render_job_match(match: JobMatch) -> None:
    st.subheader("Your profile vs this job")

    st.markdown("**Your items, ranked for this job**")
    st.dataframe(
        [
            {
                "item": i.name,
                "type": ITEM_TYPES.get(i.id.split("_")[0], ""),
                "relevance": RELEVANCE_LABELS[i.relevance],
                "why": i.reason,
            }
            for i in match.items
        ],
        hide_index=True,
        width="stretch",
    )

    st.markdown("**Relevant skills**")
    st.write(", ".join(match.relevant_skills) or "None of your skills match this job.")

    st.markdown("**Missing — not covered by your items or skills**")
    if not match.missing:
        st.write("Nothing missing — every requirement is covered.")
    for m in sorted(match.missing, key=lambda m: m.importance != "required"):
        st.markdown(f"- **{m.requirement}** ({m.importance}) — {m.note}")


def render_gap_plan(plan: GapPlan) -> None:
    st.subheader("How to close your gaps")

    if not any([plan.maybe_already_have, plan.project_add_ons, plan.new_projects,
                plan.learning, plan.not_fixable_now, plan.uncovered]):
        st.write("Nothing to close — you already cover this job's requirements.")
        return

    if plan.maybe_already_have:
        st.markdown("**Maybe you already have these — add them to your profile**")
        for hint in plan.maybe_already_have:
            st.markdown(f"- {hint}")

    if plan.project_add_ons:
        st.markdown("**Extend your existing projects**")
        for a in plan.project_add_ons:
            with st.expander(f"{a.project_name}: {a.title} ({EFFORT_LABELS[a.effort]})"):
                st.markdown(f"**Covers:** {', '.join(a.covers)}")
                st.markdown(f"**Why it fits:** {a.why_it_fits}")
                st.markdown("\n".join(f"{n}. {step}" for n, step in enumerate(a.steps, start=1)))
                st.markdown(f"**CV bullet once it's done:** _{a.cv_bullet_preview}_")

    if plan.new_projects:
        st.markdown("**New projects**")
        for n in plan.new_projects:
            with st.expander(f"{n.title} ({EFFORT_LABELS[n.effort]})"):
                st.markdown(f"**Covers:** {', '.join(n.covers)}")
                st.write(n.description)
                if n.tech_stack:
                    st.markdown(f"**Tech stack:** {', '.join(n.tech_stack)}")
                st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(n.steps, start=1)))

    if plan.learning:
        st.markdown("**Courses, certifications & docs**")
        for l in plan.learning:
            st.markdown(f"- **{l.topic}** ({l.kind}, {EFFORT_LABELS[l.effort]}) — {l.suggestion}. "
                        f"_Covers: {', '.join(l.covers)}_")

    if plan.not_fixable_now:
        st.markdown("**Can't close these quickly — address them instead**")
        for n in plan.not_fixable_now:
            st.markdown(f"- **{n.requirement}** — {n.how_to_address}")

    if plan.uncovered:
        st.markdown("**No suggestion for**")
        st.write(", ".join(plan.uncovered))


# --- CV preview -----------------------------------------------------------------------
# A rough on-screen version of the CV: the PDF's content and section order without its
# styling. Text goes through render_cv's helpers, so dates and names read as on the PDF.
# Keep it in step with render_cv_pdf when a section is added there.

def md(text: str | None) -> str:
    """CV text as literal markdown: "$50k" isn't maths and "C#" or "snake_case" isn't formatting."""
    return re.sub(r"([\\`*_\[\]<>#~|$])", r"\\\1", _clean(text))


def preview_section(title: str) -> None:
    st.markdown(f"**{title.upper()}**")


def preview_entry(title: str, date: str | None, subtitle: str | None, bullets: list[str],
                  description: str | None = None) -> None:
    """Title with its date on the right, then an italic subtitle, a description and bullets."""
    title_col, date_col = st.columns([3, 1])
    title_col.markdown(f"**{title}**" + (f"  \n*{subtitle}*" if subtitle else ""))
    if _date(date):
        date_col.caption(md(_date(date)), text_alignment="right")
    if _clean(description):
        st.markdown(md(description))
    if bullets := [b for b in bullets if _clean(b)]:
        st.markdown("\n".join(f"- {md(b)}" for b in bullets))


def render_cv_preview(cv: FinalCV, edit: bool = False, version: int = 0) -> CVRevision | None:
    """With edit, the text a revision can change (objective, skills, bullets, tech stacks) becomes
    boxes in its place, and the edits come back as a CVRevision; call it inside a form. Keys carry
    the version, so the boxes refill after an AI revision or an Undo."""
    items = []
    with st.container(border=not edit):
        if _clean(cv.name):
            st.markdown(f"## {md(cv.name)}", anchors=False)
        contact = cv.contact
        parts = [md(value) for value in (contact.email, contact.phone, contact.address) if _clean(value)] \
            if contact else []
        if parts:
            st.caption(" &nbsp;|&nbsp; ".join(parts))

        if edit:
            preview_section("Profile")
            objective = st.text_area("Profile", value=cv.objective, key=f"edit_objective_{version}",
                                     height=120, label_visibility="collapsed")
        elif _clean(cv.objective):
            preview_section("Profile")
            st.markdown(md(cv.objective))

        if edit:
            preview_section("Skills")
            skills = st.text_area("Skills", value="\n".join(cv.skills), key=f"edit_skills_{version}",
                                  placeholder="One skill per line", label_visibility="collapsed")
        elif skills := [md(s) for s in cv.skills if _clean(s)]:
            preview_section("Skills")
            st.markdown(" · ".join(skills))

        def edit_boxes(entry, has_stack: bool) -> None:
            """The entry's tech stack and bullets as boxes; items without an id can't be patched, so stay text."""
            if not entry.id:
                st.markdown("\n".join(f"- {md(b)}" for b in entry.bullets if _clean(b)))
                return
            stack = st.text_input("Tech stack", value=", ".join(entry.tech_stack),
                                  key=f"edit_stack_{entry.id}_{version}", placeholder="Comma-separated",
                                  label_visibility="collapsed") if has_stack else ""
            bullets = st.text_area("Bullets", value="\n".join(entry.bullets), key=f"edit_bullets_{entry.id}_{version}",
                                   height=150, placeholder="One bullet per line", label_visibility="collapsed")
            items.append(RevisedCVItem(id=entry.id, bullets=lines(bullets),
                                       tech_stack=[t.strip() for t in stack.split(",")] if has_stack else None))

        if cv.experience:
            preview_section("Experience")
            for exp in cv.experience:
                preview_entry(md(exp.title), exp.duration, md(exp.organization) or None, [] if edit else exp.bullets)
                if edit:
                    edit_boxes(exp, False)

        if cv.projects:
            preview_section("Projects")
            for project in cv.projects:
                title = md(_pretty_project_name(project.name))
                if url := _clean(project.repo_url):
                    href = url if re.match(r"^https?://", url) else "https://" + url
                    title += f" &nbsp;[{'GitHub' if 'github.com' in url else 'Link'}]({href})"
                if edit:
                    preview_entry(title, None, None, [])
                    edit_boxes(project, True)
                else:
                    tech = [md(t) for t in project.tech_stack if _clean(t)][:MAX_TECH_SHOWN]
                    preview_entry(title, None, " · ".join(tech) or None, project.bullets)

        if cv.education:
            preview_section("Education")
            for edu in cv.education:
                subtitle = [md(edu.institution)] if _clean(edu.institution) else []
                if _clean(edu.expected_graduation):
                    subtitle.append(f"Expected graduation {md(edu.expected_graduation)}")
                preview_entry(md(edu.degree), edu.duration, " · ".join(subtitle) or None, [], edu.description)

        if cv.courses:
            preview_section("Relevant Courses")
            course_lines = []  # not "lines", the helper the edit boxes use
            for course in cv.courses:
                line = f"- **{md(course.name)}**"
                if _clean(course.provider):
                    line += f" — {md(course.provider)}"
                if _clean(course.date):
                    line += f" ({md(course.date)})"
                course_lines.append(line)
            st.markdown("\n".join(course_lines))
    if edit:
        return CVRevision(objective=objective, skills=lines(skills), items=items)
    return None


# --- CV revisions ---------------------------------------------------------------------
# A note from the user edits the current CV (one AI call), or the user edits the text by hand
# (no AI call). Each change that actually alters the CV becomes a new version; the older ones
# are kept in cv_history for Undo.

def revise_cv(request: str) -> None:
    old = st.session_state["final_cv"]
    inputs = {  # this run's snapshot, so profile edits made since can't mix into this CV
        "structured_profile": StructuredProfile.model_validate(st.session_state["run_profile"]),
        "structured_jd": StructuredJD.model_validate(st.session_state["parsed_jd"]),
        "job_match": JobMatch.model_validate(st.session_state["job_match"]),
        "final_cv": FinalCV.model_validate(old),
        "mode": "cv",
        "revision_request": request,
    }
    result = build_application_graph().invoke(inputs)
    new, revision = result["final_cv"].model_dump(), result["cv_revision"]
    save_version(new, request, revision.changes, revision.not_done)


def save_version(new: dict, request: str, changes: list[str], not_done: list[str]) -> None:
    """Make `new` the current CV, keeping the old one for Undo. An unchanged CV makes no new version."""
    old = st.session_state["final_cv"]
    applied = new != old
    if applied:
        st.session_state["cv_history"].append(old)
        st.session_state["final_cv"] = new
        st.session_state.pop("cv_pdf_bytes", None)
    last = {"request": request, "applied": applied, "changes": changes if applied else [], "not_done": not_done}
    st.session_state["last_revision"] = last
    st.session_state.setdefault("revisions", []).append(last)


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def stop_editing() -> None:
    st.session_state["cv_editing"] = False


def editable_cv_preview(version: int) -> bool:
    """The CV preview with an Edit button that turns its text into boxes in place (no AI call).
    Saving applies them with the same code as an AI revision. True once saved, so the caller can redraw."""
    cv = FinalCV.model_validate(st.session_state["final_cv"])
    if not st.session_state.get("cv_editing"):
        st.button("✏️ Edit", on_click=lambda: st.session_state.update(cv_editing=True))
        render_cv_preview(cv)
        return False
    with st.form(f"cv_edit_{version}"):
        revision = render_cv_preview(cv, edit=True, version=version)
        save_col, cancel_col, _ = st.columns([1, 1, 4])
        saved = save_col.form_submit_button("Save", type="primary")
        cancel_col.form_submit_button("Cancel", on_click=stop_editing)
    if not saved:
        return False
    stop_editing()
    save_version(apply_revision(cv, revision).model_dump(), "Manual edit", ["Edited by hand"], [])
    return True


def undo_revision() -> None:
    st.session_state["final_cv"] = st.session_state["cv_history"].pop()
    st.session_state.pop("cv_pdf_bytes", None)
    st.session_state.pop("last_revision", None)
    st.session_state.setdefault("revisions", []).append({"undo": True})


def render_revision_result(last: dict) -> None:
    if not last["applied"]:
        st.info("No changes were made to the CV.")
    elif last["changes"]:
        st.success("**Changed:**\n" + "\n".join(f"- {md(c)}" for c in last["changes"]))
    else:
        st.success("CV updated.")
    if last["not_done"]:
        st.warning("**Not done:**\n" + "\n".join(f"- {md(n)}" for n in last["not_done"]))


st.set_page_config(page_title="JobFit", page_icon="\U0001F4DD")
st.title("JobFit")

existing = storage.load_profile()

profile_tab, jd_tab = st.tabs(["Profile", "Job Description"])

with profile_tab:
    st.caption("Fill this out once; you can come back and edit it any time.")

    st.subheader("Basics")
    name = st.text_input("Full name", value=(existing.name if existing else None) or "")

    st.subheader("Contact")
    contact = existing.contact if existing else None
    address = st.text_input("Address", value=(contact.address if contact else None) or "")
    phone = st.text_input("Phone", value=(contact.phone if contact else None) or "")
    email = st.text_input("Email", value=(contact.email if contact else None) or "")

    st.subheader("Skills & languages")
    skills_raw = st.text_input("Skills (comma-separated)", value=", ".join(existing.skills) if existing else "")
    languages_raw = st.text_input("Languages (comma-separated)", value=", ".join(existing.languages) if existing else "")

    st.subheader("Links")
    links = existing.links if existing else {}
    linkedin = st.text_input("LinkedIn URL", value=links.get("linkedin", ""))
    github = st.text_input("GitHub URL", value=links.get("github", ""))
    portfolio = st.text_input("Portfolio URL", value=links.get("portfolio", ""))

    st.subheader("Education")
    st.caption("Always included on every CV, newest first.")
    education_entries = entry_cards("education", "education", existing.education if existing else [],
                                    education_fields)

    st.subheader("Courses")
    st.caption("Only the courses relevant to a job are put on its CV.")
    course_entries = entry_cards("courses", "course", existing.courses if existing else [], course_fields)

    st.subheader("Projects")
    st.caption("Paste the GitHub link: its README is read when you add or change the link and used to write the "
               "project's bullets. Add a description for anything the README doesn't cover, or for a project "
               "without a repo.")
    project_entries = entry_cards("projects", "project", existing.projects if existing else [], project_fields)

    st.subheader("Experience")
    st.caption("The experience most relevant to a job goes on its CV, newest first.")
    experience_entries = entry_cards("experience", "experience", existing.experience if existing else [],
                                     experience_fields)

    st.subheader("Certifications")
    certification_entries = entry_cards("certifications", "certification",
                                        existing.certifications if existing else [], certification_fields)

    st.divider()
    submitted = st.button("Save profile", type="primary")

    problems = []
    refresh_readme_ids = [p["id"] for p in project_entries if p.pop("refresh_readme", False)]
    if submitted:
        for n, project in enumerate(project_entries, start=1):
            if is_blank(project):
                continue
            repo = parse_github_url(project["repo_url"])
            if not project["name"].strip() and repo:
                project["name"] = repo.path.rsplit("/", 1)[-1] if repo.path else repo.repo
            if not project["description"].strip() and not project["repo_url"].strip():
                problems.append(f"Project {n} needs a GitHub link or a description.")
            elif not project["name"].strip():
                problems.append(f"Project {n} needs a name.")
        for noun, entries, present_label in (("Education", education_entries, EDUCATION_PRESENT),
                                             ("Experience", experience_entries, EXPERIENCE_PRESENT)):
            for n, entry in enumerate(entries, start=1):
                if not is_blank(entry):
                    problems += range_problems(f"{noun} {n}", entry, present_label)
        for noun, entries in (("Course", course_entries), ("Certification", certification_entries)):
            for n, entry in enumerate(entries, start=1):
                if problem := date_problem(entry["date"], "its date", required=False):
                    problems.append(f"{noun} {n} {problem}.")

    if submitted and problems:
        st.error("\n\n".join(problems))
    elif submitted:
        links = {}
        if linkedin:
            links["linkedin"] = linkedin
        if github:
            links["github"] = github
        if portfolio:
            links["portfolio"] = portfolio

        raw_profile = {
            "name": name or None,
            "contact": {"address": address or None, "phone": phone or None, "email": email or None},
            "skills": [s.strip() for s in skills_raw.split(",") if s.strip()],
            "languages": [l.strip() for l in languages_raw.split(",") if l.strip()],
            "links": links,
            # Cards that were added but left empty are skipped.
            "education": [e for e in education_entries if not is_blank(e)],
            "courses": [c for c in course_entries if not is_blank(c)],
            "projects": [p for p in project_entries if not is_blank(p)],
            "experience": [e for e in experience_entries if not is_blank(e)],
            "certifications": [c for c in certification_entries if not is_blank(c)],
            "id_counters": dict(existing.id_counters) if existing else {},
        }

        try:
            graph = build_profile_graph()
            inputs = {"student_profile_input": raw_profile, "refresh_readme_ids": refresh_readme_ids}
            if existing is not None:
                inputs["previous_profile"] = existing  # unchanged entries keep their README and bullets
            with st.spinner("Saving profile (reading READMEs and writing bullets only where something changed)..."):
                result = graph.invoke(inputs)
            storage.save_profile(result["structured_profile"])
            # Re-seed the cards from the saved profile on the next run so new entries pick up their ids.
            for section in ("education", "courses", "projects", "experience", "certifications"):
                st.session_state.pop(f"entries_{section}", None)
            st.success("Profile saved.")
            actions = result.get("profile_actions", [])
            if actions:
                st.info("This save " + "; ".join(actions) + ".")
            else:
                st.caption("No README or bullet changes were needed, so no AI calls were made.")
            for warning in result.get("profile_warnings", []):
                st.warning(warning)
            with st.expander("Saved profile (JSON)"):
                st.json(result["structured_profile"].model_dump())
        except ValidationError as exc:
            st.error("Some fields need fixing before this profile can be saved:")
            st.code(str(exc))
        except Exception as exc:
            st.error("Something went wrong saving this profile:")
            st.code(str(exc))

with jd_tab:
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
