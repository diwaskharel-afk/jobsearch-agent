"""On-screen preview of a CV, optionally with its editable text as boxes."""
import re

import streamlit as st

from jobfit.models import CVRevision, FinalCV, RevisedCVItem
from jobfit.render_cv import MAX_TECH_SHOWN, _clean, _date, _pretty_project_name
from jobfit.ui.common import lines, md

# A rough on-screen version of the CV: the PDF's content and section order without its
# styling. Text goes through render_cv's helpers, so dates and names read as on the PDF.
# Keep it in step with render_cv_pdf when a section is added there.


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
