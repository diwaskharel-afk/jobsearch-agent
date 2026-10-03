"""The Profile tab: the profile form, its checks, and saving it through the profile graph."""
import streamlit as st
from pydantic import ValidationError

from jobfit import storage
from jobfit.github_repo import parse_github_url
from jobfit.graph import build_profile_graph
from jobfit.models import StructuredProfile
from jobfit.ui.dates import date_problem, range_problems
from jobfit.ui.profile_fields import (
    EDUCATION_PRESENT,
    EXPERIENCE_PRESENT,
    certification_fields,
    course_fields,
    education_fields,
    entry_cards,
    experience_fields,
    is_blank,
    project_fields,
)


def render_profile_tab(existing: StructuredProfile | None) -> None:
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
