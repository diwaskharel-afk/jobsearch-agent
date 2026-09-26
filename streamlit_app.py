import hashlib
import json
from datetime import datetime

import streamlit as st
from pydantic import ValidationError

import storage
from graph import build_application_graph, build_profile_graph
from llm import TASK_MODELS, model_for
from model import FinalCV, GapPlan, JobMatch, StructuredJD
from render_cv import render_cv_pdf

RELEVANCE_LABELS = {"high": "🟢 high", "medium": "🟡 medium", "low": "🟠 low", "none": "⚪ none"}
EFFORT_LABELS = {"hours": "⏱ hours", "days": "📅 days", "weeks": "🗓 weeks", "months": "📆 months"}
ITEM_TYPES = {"proj": "project", "exp": "experience", "cert": "certification", "edu": "course/education"}


def safe_filename(text: str | None, fallback: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (text or "")).strip("_") or fallback


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


st.set_page_config(page_title="Job Search Agent", page_icon="\U0001F4DD")
st.title("Job Search Agent")

existing = storage.load_profile()

profile_tab, jd_tab = st.tabs(["Profile", "Job Description"])

with profile_tab:
    st.caption("Fill this out once; you can come back and edit it any time.")

    edu_default = len(existing.education) if existing else 1
    project_default = len(existing.projects) if existing else 1
    experience_default = len(existing.experience) if existing else 0
    cert_default = len(existing.certifications) if existing else 0

    edu_count = st.number_input("How many education entries?", min_value=0, max_value=10, value=edu_default, step=1)
    project_count = st.number_input("How many projects?", min_value=0, max_value=10, value=project_default, step=1)
    experience_count = st.number_input("How many work/internship experiences?", min_value=0, max_value=10, value=experience_default, step=1)
    cert_count = st.number_input("How many certifications?", min_value=0, max_value=10, value=cert_default, step=1)

    with st.form("profile_form"):
        st.subheader("Basics")
        name = st.text_input("Full name", value=(existing.name if existing else None) or "")
        summary = st.text_area("Short summary / objective", value=(existing.summary if existing else None) or "")

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
        education_entries = []
        for i in range(edu_count):
            st.markdown(f"**Education #{i + 1}**")
            existing_edu = existing.education[i] if existing and i < len(existing.education) else None
            education_entries.append({
                "id": existing_edu.id if existing_edu else None,
                "course_name": st.text_input(f"Course/degree name #{i + 1}", value=existing_edu.course_name if existing_edu else "", key=f"edu_course_{i}"),
                "institution": st.text_input(f"Institution #{i + 1}", value=(existing_edu.institution if existing_edu else None) or "", key=f"edu_institution_{i}"),
                "description": st.text_area(f"Description #{i + 1}", value=(existing_edu.description if existing_edu else None) or "", key=f"edu_description_{i}"),
                "duration": st.text_input(f"Duration #{i + 1}", value=(existing_edu.duration if existing_edu else None) or "", key=f"edu_duration_{i}"),
            })

        st.subheader("Projects")
        project_entries = []
        for i in range(project_count):
            st.markdown(f"**Project #{i + 1}**")
            existing_proj = existing.projects[i] if existing and i < len(existing.projects) else None
            tech_default = ", ".join(existing_proj.tech_stack) if existing_proj else ""
            tech_raw = st.text_input(f"Tech stack #{i + 1} (comma-separated)", value=tech_default, key=f"proj_tech_{i}")
            project_entries.append({
                "id": existing_proj.id if existing_proj else None,
                "name": st.text_input(f"Project name #{i + 1}", value=existing_proj.name if existing_proj else "", key=f"proj_name_{i}"),
                "description": st.text_area(f"Description #{i + 1}", value=existing_proj.description if existing_proj else "", key=f"proj_description_{i}"),
                "tech_stack": [t.strip() for t in tech_raw.split(",") if t.strip()],
                "repo_url": st.text_input(f"Repo URL #{i + 1}", value=(existing_proj.repo_url if existing_proj else None) or "", key=f"proj_repo_{i}"),
                "outcomes": st.text_input(f"Outcomes #{i + 1}", value=(existing_proj.outcomes if existing_proj else None) or "", key=f"proj_outcomes_{i}"),
            })

        st.subheader("Experience")
        experience_entries = []
        for i in range(experience_count):
            st.markdown(f"**Experience #{i + 1}**")
            existing_exp = existing.experience[i] if existing and i < len(existing.experience) else None
            resp_default = "\n".join(existing_exp.responsibilities) if existing_exp else ""
            tech_default = ", ".join(existing_exp.tech_stack) if existing_exp else ""
            resp_raw = st.text_area(f"Responsibilities #{i + 1} (one per line)", value=resp_default, key=f"exp_resp_{i}")
            tech_raw = st.text_input(f"Tech stack #{i + 1} (comma-separated)", value=tech_default, key=f"exp_tech_{i}")
            experience_entries.append({
                "id": existing_exp.id if existing_exp else None,
                "title": st.text_input(f"Title #{i + 1}", value=existing_exp.title if existing_exp else "", key=f"exp_title_{i}"),
                "organization": st.text_input(f"Organization #{i + 1}", value=existing_exp.organization if existing_exp else "", key=f"exp_org_{i}"),
                "duration": st.text_input(f"Duration #{i + 1}", value=(existing_exp.duration if existing_exp else None) or "", key=f"exp_duration_{i}"),
                "responsibilities": [r.strip() for r in resp_raw.splitlines() if r.strip()],
                "tech_stack": [t.strip() for t in tech_raw.split(",") if t.strip()],
            })

        st.subheader("Certifications")
        certification_entries = []
        for i in range(cert_count):
            st.markdown(f"**Certification #{i + 1}**")
            existing_cert = existing.certifications[i] if existing and i < len(existing.certifications) else None
            certification_entries.append({
                "id": existing_cert.id if existing_cert else None,
                "name": st.text_input(f"Name #{i + 1}", value=existing_cert.name if existing_cert else "", key=f"cert_name_{i}"),
                "issuer": st.text_input(f"Issuer #{i + 1}", value=(existing_cert.issuer if existing_cert else None) or "", key=f"cert_issuer_{i}"),
                "date": st.text_input(f"Date #{i + 1}", value=(existing_cert.date if existing_cert else None) or "", key=f"cert_date_{i}"),
            })

        submitted = st.form_submit_button("Save profile")

    if submitted:
        links = {}
        if linkedin:
            links["linkedin"] = linkedin
        if github:
            links["github"] = github
        if portfolio:
            links["portfolio"] = portfolio

        raw_profile = {
            "name": name or None,
            "summary": summary or None,
            "contact": {"address": address or None, "phone": phone or None, "email": email or None},
            "skills": [s.strip() for s in skills_raw.split(",") if s.strip()],
            "languages": [l.strip() for l in languages_raw.split(",") if l.strip()],
            "links": links,
            "education": education_entries,
            "projects": project_entries,
            "experience": experience_entries,
            "certifications": certification_entries,
            "id_counters": dict(existing.id_counters) if existing else {},
        }

        try:
            graph = build_profile_graph()
            result = graph.invoke({"student_profile_input": raw_profile})
            storage.save_profile(result["structured_profile"])
            st.success("Profile saved.")
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
