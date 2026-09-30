from model import (
    BulletList,
    FinalCV,
    FinalCVCourse,
    FinalCVExperience,
    FinalCVProject,
    GapPlan,
    GeneratedCVContent,
    JobMatch,
    RankedItem,
    StructuredJD,
    StructuredProfile,
)
from state import AgentState
from github_repo import RepoFetchError, fetch_readme, parse_github_url
from llm import extract_structured
from storage import assign_profile_ids
from formatting import format_gaps, format_jd, format_job_match, format_profile, gap_ids, item_names
from prompts import (
    BULLETS_README_NOTE,
    BULLETS_SYSTEM_PROMPT,
    CV_CONTENT_SYSTEM_PROMPT,
    JD_EMPTY_REQUIREMENTS_NOTE,
    JD_SYSTEM_PROMPT,
    MATCH_PROFILE_SYSTEM_PROMPT,
    RECOMMEND_GAPS_SYSTEM_PROMPT,
)

MIN_SOURCE_LEN = 20
MAX_CV_BULLETS = 5
MAX_CV_PROJECTS = 2
MAX_CV_EXPERIENCE = 3
MAX_CV_COURSES = 4
MAX_CV_SKILLS = 20
RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
IMPORTANCE_ORDER = {"required": 0, "preferred": 1, "duty": 2}
EFFORT_ORDER = {"hours": 0, "days": 1, "weeks": 2, "months": 3}
MAX_PLAN_STEPS = 5


def intake_profile_node(state: AgentState) -> AgentState:
    raw = state.get("student_profile_input", {})
    profile = assign_profile_ids(StructuredProfile.model_validate(raw))
    return {"structured_profile": profile}


def fetch_readmes_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    if profile is None:
        return {}

    # A failed fetch never blocks saving: the project falls back to its description.
    warnings = []
    for project in profile.projects:
        project.readme = ""  # never keep a README from an earlier save or another URL
        url = (project.repo_url or "").strip()
        if not url:
            continue
        repo = parse_github_url(url)
        if repo is None:
            warnings.append(f"{project.name}: only GitHub repos can be read; the URL is kept as a CV link.")
            continue
        try:
            readme = fetch_readme(repo)
        except RepoFetchError as exc:
            warnings.append(f"{project.name}: {exc}")
            continue
        if readme:
            project.readme = readme
        else:
            warnings.append(f"{project.name}: the README of {repo} is empty.")
    return {"structured_profile": profile, "profile_warnings": warnings}


def format_bullets_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    if profile is None:
        return {}
    warnings = list(state.get("profile_warnings", []))

    for project in profile.projects:
        description = project.description.strip()
        readme = project.readme
        if len(description) + len(readme) < MIN_SOURCE_LEN:
            if not description and not readme:
                warnings.append(f"{project.name}: no description and no readable README, so no bullets were written.")
            continue
        if readme:
            sections = [f"=== DESCRIPTION ===\n{description}"] if description else []
            sections.append(f"=== REPOSITORY README ===\n{readme}")
            user_text = f"Project: {project.name}\n\n" + "\n\n".join(sections)
            system_prompt = BULLETS_SYSTEM_PROMPT + BULLETS_README_NOTE
        else:
            user_text = f"Project: {project.name}\n\n{description}"
            system_prompt = BULLETS_SYSTEM_PROMPT
        result = extract_structured("bullets", system_prompt, user_text, BulletList)
        project.bullets = result.bullets[:15]

    for experience in profile.experience:
        text = "\n".join(experience.responsibilities)
        if len(text.strip()) < MIN_SOURCE_LEN:
            continue
        user_text = f"Role: {experience.title} at {experience.organization}\n\n{text}"
        result = extract_structured("bullets", BULLETS_SYSTEM_PROMPT, user_text, BulletList)
        experience.bullets = result.bullets[:15]

    return {"structured_profile": profile, "profile_warnings": warnings}


def parse_jd_node(state: AgentState) -> AgentState:
    if state.get("structured_jd") is not None:  # reused from an earlier run on the same JD
        return {}
    raw = state.get("jd_input", "") or ""
    if not raw.strip():
        return {}
    jd = extract_structured("parse_jd", JD_SYSTEM_PROMPT, raw, StructuredJD)
    if not jd.requirements:  # matching and gap analysis depend on it, so ask once more
        retry = extract_structured("parse_jd", JD_SYSTEM_PROMPT + JD_EMPTY_REQUIREMENTS_NOTE, raw, StructuredJD)
        if retry.requirements:
            jd = retry
    return {"structured_jd": jd}


def match_profile_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    if profile is None or jd is None or state.get("job_match") is not None:
        return {}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile)}"
    )
    match = extract_structured("match", MATCH_PROFILE_SYSTEM_PROMPT, user_text, JobMatch)

    # Keep only real, unique ids, attach display names, and list any item the model skipped last.
    names = item_names(profile)
    items = {}
    for item in match.items:
        item_id = item.id.strip().strip("[]")
        if item_id in names and item_id not in items:
            items[item_id] = item.model_copy(update={"id": item_id, "name": names[item_id]})
    for item_id, name in names.items():
        items.setdefault(item_id, RankedItem(id=item_id, name=name, relevance="none", reason="not ranked"))
    match.items = sorted(items.values(), key=lambda i: RELEVANCE_ORDER[i.relevance])
    return {"job_match": match}


def generate_cv_content_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    if profile is None or jd is None or match is None:
        return {}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile)}\n\n"
        f"=== MATCH ===\n{format_job_match(match)}"
    )
    generated = extract_structured("cv", CV_CONTENT_SYSTEM_PROMPT, user_text, GeneratedCVContent)

    # Names, stacks, urls and durations always come from the saved profile, never the LLM.
    projects_by_id = {p.id: p for p in profile.projects}
    final_projects = [
        FinalCVProject(
            name=source.name,
            tech_stack=gp.tech_stack,
            repo_url=source.repo_url,
            bullets=gp.bullets[:MAX_CV_BULLETS],
        )
        for gp in generated.projects
        if (source := projects_by_id.get(gp.id.strip()))
    ][:MAX_CV_PROJECTS]

    experience_by_id = {e.id: e for e in profile.experience}
    final_experience = [
        FinalCVExperience(
            title=source.title,
            organization=source.organization,
            duration=source.duration,
            bullets=ge.bullets[:MAX_CV_BULLETS],
        )
        for ge in generated.experience
        if (source := experience_by_id.get(ge.id.strip()))
    ][:MAX_CV_EXPERIENCE]

    courses_by_id = {c.id: c for c in profile.courses}
    course_ids = dict.fromkeys(c.strip().strip("[]") for c in generated.courses)
    final_courses = [
        FinalCVCourse(name=source.name, provider=source.provider, date=source.date)
        for course_id in course_ids
        if (source := courses_by_id.get(course_id))
    ][:MAX_CV_COURSES]

    final_cv = FinalCV(
        name=profile.name,
        contact=profile.contact,
        education=profile.education,  # always on the CV, never chosen by the LLM
        courses=final_courses,
        objective=generated.objective,
        skills=generated.skills[:MAX_CV_SKILLS],
        projects=final_projects,
        experience=final_experience,
    )
    return {"final_cv": final_cv}


def route_after_match(state: AgentState) -> str:
    return "recommend_gaps" if state.get("mode") == "recommend" else "generate_cv_content"


def recommend_gaps_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    if profile is None or jd is None or match is None:
        return {}
    if not match.missing:
        return {"gap_plan": GapPlan()}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile)}\n\n"
        f"=== GAPS ===\n{format_gaps(match)}"
    )
    plan = extract_structured("gaps", RECOMMEND_GAPS_SYSTEM_PROMPT, user_text, GapPlan)

    # Keep only real gap ids and swap them for the requirement text; drop suggestions covering no real gap.
    gaps = gap_ids(match)
    covered = set()

    def resolve(items: list) -> list:
        kept = []
        for item in items:
            ids = [g for g in dict.fromkeys(c.strip().strip("[]") for c in item.covers) if g in gaps]
            if not ids:
                continue
            covered.update(ids)
            rank = (min(IMPORTANCE_ORDER[gaps[g].importance] for g in ids), EFFORT_ORDER[item.effort])
            kept.append((rank, item.model_copy(update={"covers": [gaps[g].requirement for g in ids]})))
        return [item for _, item in sorted(kept, key=lambda k: k[0])]

    project_names = {p.id: p.name for p in profile.projects}
    add_ons = []
    for a in plan.project_add_ons:
        project_id = a.project_id.strip().strip("[]")
        if project_id in project_names:
            add_ons.append(a.model_copy(update={"project_id": project_id, "project_name": project_names[project_id]}))

    not_fixable = []
    for n in plan.not_fixable_now:
        gap_id = n.requirement.strip().strip("[]")
        if gap_id in gaps:
            covered.add(gap_id)
            not_fixable.append(n.model_copy(update={"requirement": gaps[gap_id].requirement}))

    final_plan = GapPlan(
        maybe_already_have=plan.maybe_already_have,
        project_add_ons=resolve(add_ons),
        new_projects=resolve(plan.new_projects),
        learning=resolve(plan.learning),
        not_fixable_now=not_fixable,
    )
    for item in final_plan.project_add_ons + final_plan.new_projects:
        item.steps = item.steps[:MAX_PLAN_STEPS]
    final_plan.uncovered = [m.requirement for gap_id, m in gaps.items() if gap_id not in covered]
    return {"gap_plan": final_plan}
