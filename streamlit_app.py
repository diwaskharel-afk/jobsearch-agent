import json

import streamlit as st
from pydantic import ValidationError

import storage
from graph import build_application_graph, build_profile_graph
from model import FinalCV
from render_cv import render_cv_pdf

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
        }

        try:
            graph = build_profile_graph()
            result = graph.invoke({"student_profile_input": raw_profile})
            storage.save_profile(result["structured_profile"])
            st.success("Profile saved.")
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
        st.caption("Paste a job description to parse it against your saved profile.")
        with st.form("jd_form"):
            jd_text = st.text_area("Paste the job description")
            jd_submitted = st.form_submit_button("Tailor")

        if jd_submitted:
            if not jd_text.strip():
                st.warning("Paste a job description first.")
            else:
                try:
                    graph = build_application_graph()
                    result = graph.invoke({"jd_input": jd_text, "structured_profile": existing})
                    st.session_state["parsed_jd"] = result["structured_jd"].model_dump()
                    st.session_state["gap_analysis"] = result["gap_analysis"].model_dump()
                    st.session_state["final_cv"] = result["final_cv"].model_dump()
                    st.success("Job description parsed.")
                except Exception as exc:
                    st.error("Something went wrong processing this job description:")
                    st.code(str(exc))

        if st.session_state.get("parsed_jd"):
            st.json(st.session_state["parsed_jd"])
            jd_json_str = json.dumps(st.session_state["parsed_jd"], indent=2)
            title = st.session_state["parsed_jd"].get("title") or "job_description"
            safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title).strip("_") or "job_description"
            st.download_button(
                "Download parsed JD (JSON)",
                data=jd_json_str,
                file_name=f"{safe_title}_parsed.json",
                mime="application/json",
            )

        if st.session_state.get("gap_analysis"):
            st.subheader("Gap analysis")
            st.json(st.session_state["gap_analysis"])

        if st.session_state.get("final_cv"):
            st.subheader("Generated CV")
            st.caption("Review the tailored content before generating the PDF.")
            st.json(st.session_state["final_cv"])

            if st.button("Generate PDF"):
                final_cv = FinalCV.model_validate(st.session_state["final_cv"])
                st.session_state["cv_pdf_bytes"] = render_cv_pdf(final_cv)

            if st.session_state.get("cv_pdf_bytes"):
                cv_name = (st.session_state["final_cv"].get("name") or "cv").strip()
                safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cv_name).strip("_") or "cv"
                st.download_button(
                    "Download CV (PDF)",
                    data=st.session_state["cv_pdf_bytes"],
                    file_name=f"{safe_name}_cv.pdf",
                    mime="application/pdf",
                )
