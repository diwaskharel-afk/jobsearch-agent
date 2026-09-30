import hashlib
import json
from datetime import datetime
from uuid import uuid4

import streamlit as st
from pydantic import ValidationError

import storage
from github_repo import parse_github_url
from graph import build_application_graph, build_profile_graph
from llm import TASK_MODELS, model_for
from model import FinalCV, GapPlan, JobMatch, StructuredJD
from render_cv import render_cv_pdf

RELEVANCE_LABELS = {"high": "🟢 high", "medium": "🟡 medium", "low": "🟠 low", "none": "⚪ none"}
EFFORT_LABELS = {"hours": "⏱ hours", "days": "📅 days", "weeks": "🗓 weeks", "months": "📆 months"}
ITEM_TYPES = {"proj": "project", "exp": "experience", "cert": "certification", "course": "course"}


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
            title_col, remove_col = st.columns([4, 1])
            title_col.markdown(f"**{noun.capitalize()} {n}**")
            remove_col.button("🗑 Remove", key=f"{section}_{uid}_remove", on_click=remove_entry, args=(section, uid))
            values.append(render_fields(entry, lambda field, uid=uid: f"{section}_{uid}_{field}"))
    st.button(f"➕ Add {noun}", key=f"{section}_add", on_click=add_entry, args=(section,))
    return values


def optional_text_area(label: str, value: str, key: str, toggle_label: str = "Add description") -> str:
    """Text area hidden behind a checkbox; "" while the box is unticked."""
    if st.checkbox(toggle_label, value=bool(value), key=f"{key}_toggle"):
        return st.text_area(label, value=value, key=key)
    return ""


def education_fields(entry: dict, key) -> dict:
    return {
        "degree": st.text_input("Degree / programme", value=entry.get("degree") or "", key=key("degree")),
        "institution": st.text_input("Institution", value=entry.get("institution") or "", key=key("institution")),
        "duration": st.text_input("Duration", value=entry.get("duration") or "", key=key("duration")),
        "description": optional_text_area("Description", entry.get("description") or "", key("description")),
    }


def course_fields(entry: dict, key) -> dict:
    return {
        "id": entry.get("id"),
        "name": st.text_input("Course name", value=entry.get("name") or "", key=key("name")),
        "provider": st.text_input("Provider (school or platform)", value=entry.get("provider") or "", key=key("provider")),
        "date": st.text_input("Date", value=entry.get("date") or "", key=key("date")),
        "description": optional_text_area("What it covered", entry.get("description") or "", key("description"),
                                          toggle_label="Add what it covered"),
    }


def project_fields(entry: dict, key) -> dict:
    return {
        "id": entry.get("id"),
        "repo_url": st.text_input("GitHub link", value=entry.get("repo_url") or "", key=key("repo_url"),
                                  placeholder="https://github.com/you/project",
                                  help="Also shown on the CV. Private repos need a GITHUB_TOKEN in .env."),
        "name": st.text_input("Name", value=entry.get("name") or "", key=key("name"),
                              help="Leave empty to use the repo's name."),
        "description": optional_text_area("Description", entry.get("description") or "", key("description")),
    }


def experience_fields(entry: dict, key) -> dict:
    title = st.text_input("Title", value=entry.get("title") or "", key=key("title"))
    organization = st.text_input("Organization", value=entry.get("organization") or "", key=key("organization"))
    duration = st.text_input("Duration", value=entry.get("duration") or "", key=key("duration"))
    resp_raw = st.text_area("Responsibilities (one per line)", value="\n".join(entry.get("responsibilities") or []),
                            key=key("responsibilities"))
    return {
        "id": entry.get("id"),
        "title": title,
        "organization": organization,
        "duration": duration,
        "responsibilities": [r.strip() for r in resp_raw.splitlines() if r.strip()],
    }


def certification_fields(entry: dict, key) -> dict:
    return {
        "id": entry.get("id"),
        "name": st.text_input("Name", value=entry.get("name") or "", key=key("name")),
        "issuer": st.text_input("Issuer", value=entry.get("issuer") or "", key=key("issuer")),
        "date": st.text_input("Date", value=entry.get("date") or "", key=key("date")),
    }


def is_blank(entry: dict) -> bool:
    return not any(value for field, value in entry.items() if field != "id")


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
    st.caption("Always included on every CV.")
    education_entries = entry_cards("education", "education", existing.education if existing else [],
                                    education_fields)

    st.subheader("Courses")
    st.caption("Only the courses relevant to a job are put on its CV.")
    course_entries = entry_cards("courses", "course", existing.courses if existing else [], course_fields)

    st.subheader("Projects")
    st.caption("Paste the GitHub link: its README is read on every save and used to write the project's bullets. "
               "Add a description for anything the README doesn't cover, or for a project without a repo.")
    project_entries = entry_cards("projects", "project", existing.projects if existing else [], project_fields)

    st.subheader("Experience")
    experience_entries = entry_cards("experience", "experience", existing.experience if existing else [],
                                     experience_fields)

    st.subheader("Certifications")
    certification_entries = entry_cards("certifications", "certification",
                                        existing.certifications if existing else [], certification_fields)

    st.divider()
    submitted = st.button("Save profile", type="primary")

    problems = []
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
            with st.spinner("Reading repo READMEs and writing bullets..."):
                result = graph.invoke({"student_profile_input": raw_profile})
            storage.save_profile(result["structured_profile"])
            # Re-seed the cards from the saved profile on the next run so new entries pick up their ids.
            for section in ("education", "courses", "projects", "experience", "certifications"):
                st.session_state.pop(f"entries_{section}", None)
            st.success("Profile saved.")
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
                        for key in ("final_cv", "cv_pdf_bytes", "gap_plan"):
                            st.session_state.pop(key, None)

                    result = build_application_graph().invoke(inputs)
                    st.session_state["match_key"] = match_key
                    st.session_state["jd_input"] = jd_text
                    st.session_state["run_profile"] = existing.model_dump()
                    st.session_state["parsed_jd"] = result["structured_jd"].model_dump()
                    st.session_state["job_match"] = result["job_match"].model_dump()
                    if mode == "cv":
                        st.session_state["final_cv"] = result["final_cv"].model_dump()
                        st.session_state.pop("cv_pdf_bytes", None)
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
            st.subheader("Generated CV")
            st.caption("The tailored content is under Raw data & download → Generated CV.")

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
                    ("Generated CV", run["final_cv"]),
                    ("Profile used for this run", run["structured_profile"]),
                    ("Models used", run["models"]),
                ]
                for label, data in raw_sections:
                    if data:
                        with st.expander(label):
                            st.json(data)
