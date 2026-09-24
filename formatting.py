from model import GapAnalysis, StructuredJD, StructuredProfile


def format_jd(jd: StructuredJD) -> str:
    lines = [f"Title: {jd.title}"]
    if jd.company:
        lines.append(f"Company: {jd.company}")
    if jd.seniority:
        lines.append(f"Seniority: {jd.seniority}")
    if jd.required_skills:
        lines.append(f"Required skills: {', '.join(jd.required_skills)}")
    if jd.preferred_skills:
        lines.append(f"Preferred skills: {', '.join(jd.preferred_skills)}")
    if jd.tech_stack:
        lines.append(f"Tech stack: {', '.join(jd.tech_stack)}")
    if jd.keywords:
        lines.append(f"Keywords: {', '.join(jd.keywords)}")
    if jd.responsibilities:
        lines.append("Responsibilities:")
        lines.extend(f"- {item}" for item in jd.responsibilities)
    return "\n".join(lines)


def format_profile_for_gap_analysis(profile: StructuredProfile) -> str:
    sections = []

    if profile.skills:
        sections.append(f"Skills: {', '.join(profile.skills)}")

    for project in profile.projects:
        lines = [f"Project: {project.name}"]
        if project.tech_stack:
            lines.append(f"Tech stack: {', '.join(project.tech_stack)}")
        lines.extend(f"- {bullet}" for bullet in project.bullets)
        sections.append("\n".join(lines))

    for experience in profile.experience:
        lines = [f"Experience: {experience.title} at {experience.organization}"]
        if experience.tech_stack:
            lines.append(f"Tech stack: {', '.join(experience.tech_stack)}")
        lines.extend(f"- {bullet}" for bullet in experience.bullets)
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def format_gap_analysis(gap: GapAnalysis) -> str:
    lines = []
    if gap.matched_skills:
        lines.append(f"Matched skills: {', '.join(gap.matched_skills)}")
    if gap.missing_required_skills:
        lines.append(f"Missing required skills: {', '.join(gap.missing_required_skills)}")
    if gap.missing_preferred_skills:
        lines.append(f"Missing preferred skills: {', '.join(gap.missing_preferred_skills)}")
    if gap.relevant_projects:
        lines.append(f"Relevant projects: {', '.join(gap.relevant_projects)}")
    if gap.relevant_experience:
        lines.append(f"Relevant experience: {', '.join(gap.relevant_experience)}")
    if gap.low_relevance_projects:
        lines.append(f"Low-relevance projects: {', '.join(gap.low_relevance_projects)}")
    if gap.notes:
        lines.append(f"Notes: {gap.notes}")
    return "\n".join(lines)
