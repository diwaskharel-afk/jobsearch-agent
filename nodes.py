from model import (
    BulletList,
    FinalCV,
    FinalCVExperience,
    FinalCVProject,
    GapAnalysis,
    GeneratedCVContent,
    StructuredJD,
    StructuredProfile,
)
from state import AgentState
from llm import extract_structured
from formatting import format_gap_analysis, format_jd, format_profile_for_gap_analysis
from prompts import (
    CV_CONTENT_SYSTEM_PROMPT,
    EXPERIENCE_BULLETS_SYSTEM_PROMPT,
    GAP_ANALYSIS_SYSTEM_PROMPT,
    JD_SYSTEM_PROMPT,
    PROJECT_BULLETS_SYSTEM_PROMPT,
)

MIN_SOURCE_LEN = 20
MAX_CV_BULLETS = 5
MAX_CV_PROJECTS = 4
MAX_CV_EXPERIENCE = 4


def intake_profile_node(state: AgentState) -> AgentState:
    raw = state.get("student_profile_input", {})
    profile = StructuredProfile.model_validate(raw)
    return {"structured_profile": profile}


def format_bullets_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    if profile is None:
        return {}

    for project in profile.projects:
        text = project.description or ""
        if project.outcomes:
            text = f"{text}\nOutcomes: {project.outcomes}"
        if len(text.strip()) < MIN_SOURCE_LEN:
            continue
        header = f"Project: {project.name}"
        if project.tech_stack:
            header += f"\nTech stack: {', '.join(project.tech_stack)}"
        user_text = f"{header}\n\n{text}"
        result = extract_structured(PROJECT_BULLETS_SYSTEM_PROMPT, user_text, BulletList)
        project.bullets = result.bullets[:15]

    for experience in profile.experience:
        text = "\n".join(experience.responsibilities)
        if len(text.strip()) < MIN_SOURCE_LEN:
            continue
        header = f"Role: {experience.title} at {experience.organization}"
        if experience.tech_stack:
            header += f"\nTech stack: {', '.join(experience.tech_stack)}"
        user_text = f"{header}\n\n{text}"
        result = extract_structured(EXPERIENCE_BULLETS_SYSTEM_PROMPT, user_text, BulletList)
        experience.bullets = result.bullets[:15]

    return {"structured_profile": profile}


def parse_jd_node(state: AgentState) -> AgentState:
    raw = state.get("jd_input", "") or ""
    if not raw.strip():
        return {}
    structured_jd = extract_structured(JD_SYSTEM_PROMPT, raw, StructuredJD)
    return {"structured_jd": structured_jd}


def gap_analysis_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    if profile is None or jd is None:
        return {}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile_for_gap_analysis(profile)}"
    )
    result = extract_structured(GAP_ANALYSIS_SYSTEM_PROMPT, user_text, GapAnalysis)
    return {"gap_analysis": result}


def generate_cv_content_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    gap = state.get("gap_analysis")
    if profile is None or jd is None or gap is None:
        return {}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile_for_gap_analysis(profile)}\n\n"
        f"=== GAP ANALYSIS ===\n{format_gap_analysis(gap)}"
    )
    generated = extract_structured(CV_CONTENT_SYSTEM_PROMPT, user_text, GeneratedCVContent)

    projects_by_name = {p.name.strip().lower(): p for p in profile.projects}
    final_projects = []
    for gp in generated.projects[:MAX_CV_PROJECTS]:
        source = projects_by_name.get(gp.name.strip().lower())
        if source is None:
            continue
        final_projects.append(FinalCVProject(
            name=source.name,
            tech_stack=source.tech_stack,
            repo_url=source.repo_url,
            bullets=gp.bullets[:MAX_CV_BULLETS],
        ))

    experience_by_key = {
        (e.title.strip().lower(), e.organization.strip().lower()): e for e in profile.experience
    }
    final_experience = []
    for ge in generated.experience[:MAX_CV_EXPERIENCE]:
        source = experience_by_key.get((ge.title.strip().lower(), ge.organization.strip().lower()))
        if source is None:
            continue
        final_experience.append(FinalCVExperience(
            title=source.title,
            organization=source.organization,
            duration=source.duration,
            bullets=ge.bullets[:MAX_CV_BULLETS],
        ))

    known_skills = {s.strip().lower() for s in profile.skills}
    final_skills = [s for s in generated.skills if s.strip().lower() in known_skills]

    final_cv = FinalCV(
        name=profile.name,
        contact=profile.contact,
        education=profile.education,
        objective=generated.objective,
        skills=final_skills,
        projects=final_projects,
        experience=final_experience,
    )
    return {"final_cv": final_cv}
