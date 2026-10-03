import hashlib

from langgraph.graph import END

from jobfit.models import (
    BulletList,
    CVRevision,
    FinalCV,
    FinalCVCourse,
    FinalCVEducation,
    FinalCVExperience,
    FinalCVProject,
    GapPlan,
    GeneratedCVContent,
    JobMatch,
    ProfileExperience,
    ProfileProject,
    RankedItem,
    StructuredJD,
    StructuredProfile,
)
from jobfit.state import AgentState
from jobfit.github_repo import RepoFetchError, fetch_readme, parse_github_url
from jobfit.llm import extract_structured, model_for
from jobfit.storage import assign_profile_ids
from jobfit.formatting import (
    format_cv_for_revision,
    format_gaps,
    format_jd,
    format_job_match,
    format_missing,
    format_month,
    format_profile,
    format_range,
    gap_ids,
    item_names,
    recency_key,
)
from jobfit.prompts import (
    BULLETS_README_NOTE,
    BULLETS_SYSTEM_PROMPT,
    CV_CONTENT_SYSTEM_PROMPT,
    JD_EMPTY_REQUIREMENTS_NOTE,
    JD_SYSTEM_PROMPT,
    MATCH_PROFILE_SYSTEM_PROMPT,
    RECOMMEND_GAPS_SYSTEM_PROMPT,
    REVISE_CV_SYSTEM_PROMPT,
)

MIN_SOURCE_LEN = 20
MAX_PROFILE_BULLETS = 15
MAX_CV_BULLETS = 5
MAX_CV_PROJECTS = 2
MAX_CV_EXPERIENCE = 2
MAX_CV_COURSES = 4
MAX_CV_SKILLS = 20
RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
IMPORTANCE_ORDER = {"required": 0, "preferred": 1, "duty": 2}
EFFORT_ORDER = {"hours": 0, "days": 1, "weeks": 2, "months": 3}
MAX_PLAN_STEPS = 5


def intake_profile_node(state: AgentState) -> AgentState:
    raw = state.get("student_profile_input", {})
    profile = assign_profile_ids(StructuredProfile.model_validate(raw))

    # The form only sends what the user typed. READMEs and bullets come from the saved entry
    # with the same id, so the next nodes only redo the work for what actually changed.
    previous = state.get("previous_profile")
    if previous is not None:
        saved_projects = {p.id: p for p in previous.projects}
        for project in profile.projects:
            if saved := saved_projects.get(project.id):
                if (saved.repo_url or "").strip() == (project.repo_url or "").strip():
                    project.readme = saved.readme
                project.bullets, project.bullets_source = list(saved.bullets), saved.bullets_source
        saved_experience = {e.id: e for e in previous.experience}
        for experience in profile.experience:
            if saved := saved_experience.get(experience.id):
                experience.bullets, experience.bullets_source = list(saved.bullets), saved.bullets_source
    return {"structured_profile": profile}


def fetch_readmes_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    if profile is None:
        return {}

    # A README kept from the last save is reused, unless the user asked to re-read it.
    # A missing one (new or changed link, or a fetch that failed last time) is fetched.
    # A failed fetch never blocks saving: the project falls back to its description.
    refresh = set(state.get("refresh_readme_ids", []))
    warnings = []
    actions = list(state.get("profile_actions", []))
    for project in profile.projects:
        url = (project.repo_url or "").strip()
        if not url:
            project.readme = ""
            continue
        if project.readme and project.id not in refresh:
            continue
        project.readme = ""
        repo = parse_github_url(url)
        if repo is None:
            warnings.append(f"{project.name}: only GitHub repos can be read; the URL is kept as a CV link.")
            continue
        try:
            readme = fetch_readme(repo)
        except RepoFetchError as exc:
            warnings.append(f"{project.name}: {exc}")
            continue
        actions.append(f"read the README of {repo}")
        if readme:
            project.readme = readme
        else:
            warnings.append(f"{project.name}: the README of {repo} is empty.")
    return {"structured_profile": profile, "profile_warnings": warnings, "profile_actions": actions}


def project_bullets_prompt(project: ProfileProject) -> tuple[str, str] | None:
    """(system prompt, user text) for a project's bullets; None if there is too little text to write them from."""
    description = project.description.strip()
    readme = project.readme
    if len(description) + len(readme) < MIN_SOURCE_LEN:
        return None
    if not readme:
        return BULLETS_SYSTEM_PROMPT, f"Project: {project.name}\n\n{description}"
    sections = [f"=== DESCRIPTION ===\n{description}"] if description else []
    sections.append(f"=== REPOSITORY README ===\n{readme}")
    return BULLETS_SYSTEM_PROMPT + BULLETS_README_NOTE, f"Project: {project.name}\n\n" + "\n\n".join(sections)


def experience_bullets_prompt(experience: ProfileExperience) -> tuple[str, str] | None:
    """(system prompt, user text) for an experience's bullets; None if there is too little text to write them from."""
    text = "\n".join(experience.responsibilities)
    if len(text.strip()) < MIN_SOURCE_LEN:
        return None
    return BULLETS_SYSTEM_PROMPT, f"Role: {experience.title} at {experience.organization}\n\n{text}"


def refresh_bullets(item: ProfileProject | ProfileExperience, prompt: tuple[str, str] | None) -> int | None:
    """Write the item's bullets unless the exact same request wrote the ones it has.
    None if the LLM wasn't called, else how many bullets past MAX_PROFILE_BULLETS were dropped."""
    if prompt is None:
        item.bullets, item.bullets_source = [], ""
        return None
    system_prompt, user_text = prompt
    source = hashlib.sha256("\n\n".join((model_for("bullets"), system_prompt, user_text)).encode()).hexdigest()
    if item.bullets and item.bullets_source == source:
        return None
    bullets = extract_structured("bullets", system_prompt, user_text, BulletList).bullets
    item.bullets = bullets[:MAX_PROFILE_BULLETS]
    item.bullets_source = source
    return max(len(bullets) - MAX_PROFILE_BULLETS, 0)


def bullet_warning(name: str, dropped: int) -> str:
    return (f"{name}: the model wrote {MAX_PROFILE_BULLETS + dropped} bullets and only the first "
            f"{MAX_PROFILE_BULLETS} were kept. Check that nothing important is missing.")


def format_bullets_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    if profile is None:
        return {}
    warnings = list(state.get("profile_warnings", []))
    actions = list(state.get("profile_actions", []))

    for project in profile.projects:
        prompt = project_bullets_prompt(project)
        if prompt is None and not project.description.strip() and not project.readme:
            warnings.append(f"{project.name}: no description and no readable README, so no bullets were written.")
        dropped = refresh_bullets(project, prompt)
        if dropped is not None:
            actions.append(f"wrote bullets for {project.name}")
        if dropped:
            warnings.append(bullet_warning(project.name, dropped))

    for experience in profile.experience:
        name = f"{experience.title} at {experience.organization}"
        dropped = refresh_bullets(experience, experience_bullets_prompt(experience))
        if dropped is not None:
            actions.append(f"wrote bullets for {name}")
        if dropped:
            warnings.append(bullet_warning(name, dropped))

    return {"structured_profile": profile, "profile_warnings": warnings, "profile_actions": actions}


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
    if state.get("final_cv") is not None:  # revising a CV generated in an earlier run
        return {}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile)}\n\n"
        f"=== MATCH ===\n{format_job_match(match)}"
    )
    generated = extract_structured("cv", CV_CONTENT_SYSTEM_PROMPT, user_text, GeneratedCVContent)

    # Names, stacks, urls and dates always come from the saved profile, never the LLM.
    projects_by_id = {p.id: p for p in profile.projects}
    final_projects = [
        FinalCVProject(
            id=source.id,
            name=source.name,
            tech_stack=gp.tech_stack,
            repo_url=source.repo_url,
            bullets=gp.bullets[:MAX_CV_BULLETS],
        )
        for gp in generated.projects
        if (source := projects_by_id.get(gp.id.strip()))
    ][:MAX_CV_PROJECTS]

    # The LLM picks experience by relevance; the CV lists the picked ones newest first.
    experience_by_id = {e.id: e for e in profile.experience}
    picked_experience = [
        (source, ge)
        for ge in generated.experience
        if (source := experience_by_id.get(ge.id.strip()))
    ][:MAX_CV_EXPERIENCE]
    final_experience = [
        FinalCVExperience(
            id=source.id,
            title=source.title,
            organization=source.organization,
            duration=format_range(source),
            bullets=ge.bullets[:MAX_CV_BULLETS],
        )
        for source, ge in sorted(picked_experience, key=lambda pick: recency_key(pick[0]), reverse=True)
    ]

    courses_by_id = {c.id: c for c in profile.courses}
    course_ids = dict.fromkeys(c.strip().strip("[]") for c in generated.courses)
    final_courses = [
        FinalCVCourse(name=source.name, provider=source.provider, date=format_month(source.date) or None)
        for course_id in course_ids
        if (source := courses_by_id.get(course_id))
    ][:MAX_CV_COURSES]

    final_cv = FinalCV(
        name=profile.name,
        contact=profile.contact,
        education=[  # always on the CV, never chosen by the LLM
            FinalCVEducation(degree=edu.degree, institution=edu.institution, description=edu.description,
                             duration=format_range(edu),
                             expected_graduation=format_month(edu.expected_graduation) or None)
            for edu in sorted(profile.education, key=recency_key, reverse=True)
        ],
        courses=final_courses,
        objective=generated.objective,
        skills=generated.skills[:MAX_CV_SKILLS],
        projects=final_projects,
        experience=final_experience,
    )
    return {"final_cv": final_cv}


def route_after_match(state: AgentState) -> str:
    return "recommend_gaps" if state.get("mode") == "recommend" else "generate_cv_content"


def route_after_cv(state: AgentState) -> str:
    return "revise_cv" if (state.get("revision_request") or "").strip() else END


def clean_list(values: list[str] | None) -> list[str]:
    """Trimmed and non-empty, keeping the first spelling of each value (case-insensitive)."""
    seen, kept = set(), []
    for value in (v.strip() for v in values or []):
        if value and value.lower() not in seen:
            seen.add(value.lower())
            kept.append(value)
    return kept


def apply_revision(cv: FinalCV, revision: CVRevision) -> FinalCV:
    """A copy of the CV with the revision applied. Empty values count as unchanged, only items
    already on the CV can change, and names, links, dates, education and courses are always kept."""
    patches = {}
    for item in revision.items:
        patches.setdefault(item.id.strip().strip("[]"), item)

    def patched(entry: FinalCVProject | FinalCVExperience, has_stack: bool):
        patch = patches.get(entry.id)
        if patch is None:
            return entry
        update = {}
        if bullets := [b.strip() for b in patch.bullets or [] if b.strip()]:
            update["bullets"] = bullets[:MAX_CV_BULLETS]
        if has_stack and (stack := clean_list(patch.tech_stack)):
            update["tech_stack"] = stack
        return entry.model_copy(update=update)

    return cv.model_copy(update={
        "objective": (revision.objective or "").strip() or cv.objective,
        "skills": clean_list(revision.skills)[:MAX_CV_SKILLS] or cv.skills,
        "projects": [patched(p, True) for p in cv.projects],
        "experience": [patched(e, False) for e in cv.experience],
    })


def revise_cv_node(state: AgentState) -> AgentState:
    cv = state.get("final_cv")
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    request = (state.get("revision_request") or "").strip()
    if cv is None or profile is None or jd is None or match is None or not request:
        return {}

    # Only the CV's own items: the model can't move facts between items or add new ones.
    on_cv = {p.id for p in cv.projects} | {e.id for e in cv.experience}
    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile, only_ids=on_cv)}\n\n"
        f"=== NEVER CLAIM ===\n{format_missing(match) or 'Nothing.'}\n\n"
        f"=== CURRENT CV ===\n{format_cv_for_revision(cv)}\n\n"
        f"=== REQUEST ===\n{request}"
    )
    revision = extract_structured("revise", REVISE_CV_SYSTEM_PROMPT, user_text, CVRevision)
    return {"final_cv": apply_revision(cv, revision), "cv_revision": revision}


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
