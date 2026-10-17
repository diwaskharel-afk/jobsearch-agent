import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from langgraph.graph import END

from jobfit.models import (
    BulletList,
    CourseEntry,
    CourseList,
    CoverLetter,
    CoverLetterRevision,
    CVRevision,
    CVSwap,
    FinalCV,
    FinalCVCourse,
    FinalCVEducation,
    FinalCVExperience,
    FinalCVProject,
    GapPlan,
    GeneratedCVContent,
    GeneratedCVItem,
    GeneratedCoverLetter,
    JobMatch,
    ProfileExperience,
    ProfileProject,
    ProjectPlan,
    RankedItem,
    StructuredJD,
    StructuredProfile,
)
from jobfit.state import AgentState
from jobfit.github_repo import RepoFetchError, fetch_readme, parse_github_url
from jobfit.llm import extract_structured, model_for
from jobfit.render_cv import _pretty_project_name
from jobfit.storage import assign_profile_ids
from jobfit.formatting import (
    format_cv_for_revision,
    format_gaps,
    format_jd,
    format_job_match,
    format_letter_body,
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
    COVER_LETTER_SYSTEM_PROMPT,
    CV_CONTENT_SYSTEM_PROMPT,
    JD_EMPTY_REQUIREMENTS_NOTE,
    JD_SYSTEM_PROMPT,
    MATCH_PROFILE_SYSTEM_PROMPT,
    RECOMMEND_COURSES_SYSTEM_PROMPT,
    RECOMMEND_PROJECTS_SYSTEM_PROMPT,
    REVISE_COVER_LETTER_SYSTEM_PROMPT,
    REVISE_CV_SYSTEM_PROMPT,
    SWAP_CV_ITEM_SYSTEM_PROMPT,
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
MAX_PLAN_ADD_ONS = 2
MAX_PLAN_NEW_PROJECTS = 1
MAX_PLAN_COURSES = 3
MAX_LETTER_PARAGRAPHS = 6

# What goes into each document is picked in code from the match ranking (best first); the
# LLMs that write the CV and the cover letter never see the other items and never choose.
# A CV has limited room, so each kind of item has a cap; the letter takes every relevant item.
# Only these levels are used, even if that leaves a CV section short or empty.
CV_RELEVANCE = ("high", "medium")
CV_LIMITS = {"proj": MAX_CV_PROJECTS, "exp": MAX_CV_EXPERIENCE, "course": MAX_CV_COURSES}  # no certifications
LETTER_RELEVANCE = ("high", "medium")


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


def pick_for_cv(match: JobMatch) -> list[str]:
    """Ids of the items that go on the CV: the best-ranked of each kind at CV_RELEVANCE, up to CV_LIMITS."""
    picked, counts = [], {}
    for item in match.items:  # best first
        kind = item.id.split("_")[0]
        if item.relevance in CV_RELEVANCE and counts.get(kind, 0) < CV_LIMITS.get(kind, 0):
            counts[kind] = counts.get(kind, 0) + 1
            picked.append(item.id)
    return picked


def pick_for_letter(match: JobMatch) -> list[str]:
    """Ids of every item at LETTER_RELEVANCE, best first, however many there are."""
    return [item.id for item in match.items if item.relevance in LETTER_RELEVANCE]


# A CV item is built from its profile entry: names, links and dates always come from there.
# `written` is what the LLM wrote for it; without it (or without bullets) the profile bullets are used.

def cv_project(source: ProfileProject, written: GeneratedCVItem | None) -> FinalCVProject:
    return FinalCVProject(
        id=source.id,
        name=source.name,
        tech_stack=written.tech_stack if written else [],
        repo_url=source.repo_url,
        bullets=((written.bullets if written else []) or source.bullets)[:MAX_CV_BULLETS],
    )


def cv_experience(source: ProfileExperience, written: GeneratedCVItem | None) -> FinalCVExperience:
    return FinalCVExperience(
        id=source.id,
        title=source.title,
        organization=source.organization,
        duration=format_range(source),
        bullets=((written.bullets if written else []) or source.bullets or source.responsibilities)[:MAX_CV_BULLETS],
    )


def cv_course(source: CourseEntry) -> FinalCVCourse:
    return FinalCVCourse(id=source.id, name=source.name, provider=source.provider,
                         date=format_month(source.date) or None)


def cv_item_ids(cv: FinalCV) -> list[str]:
    """Profile ids of the projects, experience and courses on the CV, in CV order."""
    return [entry.id for entry in cv.experience + cv.projects + cv.courses if entry.id]


def generate_cv_content_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    if profile is None or jd is None or match is None:
        return {}
    if state.get("final_cv") is not None:  # revising a CV generated in an earlier run
        return {}

    picked = pick_for_cv(match)
    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile, only_ids=set(picked))}\n\n"
        f"=== MATCH ===\n{format_job_match(match, only_ids=set(picked))}"
    )
    generated = extract_structured("cv", CV_CONTENT_SYSTEM_PROMPT, user_text, GeneratedCVContent)

    # The LLM writes the bullets and stacks; which items appear, their names, urls and dates
    # always come from the picks and the saved profile. An item the LLM skipped keeps its
    # profile bullets, so every picked item is on the CV.
    written = {}
    for item in generated.projects + generated.experience:
        written.setdefault(item.id.strip().strip("[]"), item)
    projects_by_id = {p.id: p for p in profile.projects}
    final_projects = [cv_project(source, written.get(source.id))
                      for item_id in picked if (source := projects_by_id.get(item_id))]

    # Picked by relevance, listed newest first.
    experience_by_id = {e.id: e for e in profile.experience}
    picked_experience = [source for item_id in picked if (source := experience_by_id.get(item_id))]
    final_experience = [cv_experience(source, written.get(source.id))
                        for source in sorted(picked_experience, key=recency_key, reverse=True)]

    courses_by_id = {c.id: c for c in profile.courses}
    final_courses = [cv_course(source) for item_id in picked if (source := courses_by_id.get(item_id))]

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
    branches = {"analyse": END, "recommend": "recommend_gaps", "cover_letter": "generate_cover_letter"}
    return branches.get(state.get("mode"), "generate_cv_content")


def route_after_cv(state: AgentState) -> str:
    if (state.get("swap_out") or "").strip():
        return "swap_cv_item"
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


def swap_candidates(cv: FinalCV, item_id: str, match: JobMatch) -> list[RankedItem]:
    """Profile items that can take item_id's place: the same kind, not on the CV, best-ranked first."""
    kind = item_id.split("_")[0]
    on_cv = set(cv_item_ids(cv))
    return [item for item in match.items if item.id.split("_")[0] == kind and item.id not in on_cv]


def swap_cv_item_node(state: AgentState) -> AgentState:
    """Replace one item on the CV with another of the same kind from the profile. The user chose
    both, and code swaps them; for a project or experience, the LLM writes the new item's bullets
    (and stack) and keeps the objective and skills in step. A course has no written text, so no LLM."""
    cv = state.get("final_cv")
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    old_id = (state.get("swap_out") or "").strip()
    new_id = (state.get("swap_in") or "").strip()
    if cv is None or profile is None or jd is None or match is None or not old_id:
        return {}
    if old_id not in cv_item_ids(cv):
        raise ValueError(f"{old_id} is not on the CV")
    if new_id not in {item.id for item in swap_candidates(cv, old_id, match)}:
        raise ValueError(f"{new_id} can't replace {old_id}: it must be a profile item of the same kind, not on the CV")

    names = item_names(profile)
    swapped = f"Swapped {names.get(old_id, old_id)} for {names[new_id]}"
    if new_id.startswith("course_"):
        source = next(c for c in profile.courses if c.id == new_id)
        courses = [cv_course(source) if c.id == old_id else c for c in cv.courses]
        return {"final_cv": cv.model_copy(update={"courses": courses}), "cv_swap": CVSwap(changes=[swapped])}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== NEW ITEM ===\n{format_profile(profile, only_ids={new_id})}\n\n"
        f"=== MATCH ===\n{format_job_match(match, only_ids={new_id})}\n\n"
        f"=== CURRENT CV ===\n{format_cv_for_revision(cv)}\n\n"
        f"=== SWAP ===\nReplace [{old_id}] {names.get(old_id, old_id)} with [{new_id}] {names[new_id]}."
    )
    swap = extract_structured("swap", SWAP_CV_ITEM_SYSTEM_PROMPT, user_text, CVSwap)
    written = GeneratedCVItem(id=new_id, tech_stack=clean_list(swap.tech_stack),
                              bullets=[b.strip() for b in swap.bullets if b.strip()])

    update = {
        "objective": (swap.objective or "").strip() or cv.objective,
        "skills": clean_list(swap.skills)[:MAX_CV_SKILLS] or cv.skills,
    }
    if new_id.startswith("proj_"):  # takes the old project's place
        source = next(p for p in profile.projects if p.id == new_id)
        update["projects"] = [cv_project(source, written) if p.id == old_id else p for p in cv.projects]
    else:  # experience stays newest first
        source = next(e for e in profile.experience if e.id == new_id)
        experience = [cv_experience(source, written) if e.id == old_id else e for e in cv.experience]
        dates = {e.id: recency_key(e) for e in profile.experience}
        update["experience"] = sorted(experience, key=lambda e: dates.get(e.id, ("", "")), reverse=True)
    return {"final_cv": cv.model_copy(update=update),
            "cv_swap": swap.model_copy(update={"changes": [swapped] + swap.changes})}


def strip_citations(text: str) -> str:
    """Web search adds source links to its text, e.g. "... skills. ([site.com](https://...))"; the card links the page."""
    text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", text)  # a "([site](url))" citation goes
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).strip()  # any other link keeps its text


def strip_tracking(url: str) -> str:
    """The URL without utm_ parameters (web search adds utm_source=openai)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(query)))


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
    # Two calls, so only the course search pays for web search; they run side by side.
    with ThreadPoolExecutor(max_workers=2) as pool:
        projects_call = pool.submit(extract_structured, "gaps", RECOMMEND_PROJECTS_SYSTEM_PROMPT, user_text,
                                    ProjectPlan)
        courses_call = pool.submit(extract_structured, "courses", RECOMMEND_COURSES_SYSTEM_PROMPT, user_text,
                                   CourseList, web_search=True)
        projects, courses = projects_call.result(), courses_call.result()

    # Keep only real gap ids and swap them for the requirement text; drop suggestions covering no real gap.
    gaps = gap_ids(match)

    def resolve(items: list, limit: int) -> list:
        kept = []
        for item in items:
            ids = [g for g in dict.fromkeys(c.strip().strip("[]") for c in item.covers) if g in gaps]
            if not ids:
                continue
            rank = (min(IMPORTANCE_ORDER[gaps[g].importance] for g in ids), EFFORT_ORDER[item.effort])
            kept.append((rank, item.model_copy(update={"covers": [gaps[g].requirement for g in ids]})))
        return [item for _, item in sorted(kept, key=lambda k: k[0])][:limit]

    project_names = {p.id: p.name for p in profile.projects}
    add_ons = []
    for a in projects.project_add_ons:
        project_id = a.project_id.strip().strip("[]")
        if project_id in project_names:
            add_ons.append(a.model_copy(update={"project_id": project_id, "project_name": project_names[project_id]}))

    found = []
    for c in courses.courses:  # a link that isn't a web address is dropped, not shown
        url = c.url.strip()
        found.append(c.model_copy(update={
            "url": strip_tracking(url) if url.startswith(("https://", "http://")) else "",
            "title": strip_citations(c.title), "why": strip_citations(c.why),
        }))

    final_plan = GapPlan(
        project_add_ons=resolve(add_ons, MAX_PLAN_ADD_ONS),
        new_projects=resolve(projects.new_projects, MAX_PLAN_NEW_PROJECTS),
        courses=resolve(found, MAX_PLAN_COURSES),
    )
    for item in final_plan.project_add_ons + final_plan.new_projects:
        item.steps = item.steps[:MAX_PLAN_STEPS]
    return {"gap_plan": final_plan}


def clean_paragraphs(paragraphs: list[str] | None) -> list[str]:
    """Trimmed, non-empty paragraphs, each on one line, at most MAX_LETTER_PARAGRAPHS."""
    return [" ".join(p.split()) for p in paragraphs or [] if p.strip()][:MAX_LETTER_PARAGRAPHS]


def generate_cover_letter_node(state: AgentState) -> AgentState:
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    if profile is None or jd is None or match is None:
        return {}
    if state.get("cover_letter") is not None:  # revising a letter written in an earlier run
        return {}

    picked = pick_for_letter(match)
    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile, only_ids=set(picked))}\n\n"
        f"=== MATCH ===\n{format_job_match(match, only_ids=set(picked))}"
    )
    generated = extract_structured("letter", COVER_LETTER_SYSTEM_PROMPT, user_text, GeneratedCoverLetter)

    # Everything around the body comes from the profile and the JD, never the LLM.
    company = (jd.company or "").strip() or None
    today = date.today()
    letter = CoverLetter(
        name=profile.name,
        contact=profile.contact,
        date=f"{today.day} {today:%B %Y}",
        job_title=jd.title,
        company=company,
        greeting=f"Dear {company} team," if company else "Dear Hiring Manager,",
        paragraphs=clean_paragraphs(generated.paragraphs),
        source_ids=picked,
    )
    return {"cover_letter": letter}


def route_after_letter(state: AgentState) -> str:
    return "revise_cover_letter" if (state.get("letter_revision_request") or "").strip() else END


def apply_letter_revision(letter: CoverLetter, revision: CoverLetterRevision) -> CoverLetter:
    """A copy of the letter with the revised body; an empty body counts as unchanged."""
    return letter.model_copy(update={"paragraphs": clean_paragraphs(revision.paragraphs) or letter.paragraphs})


def revise_cover_letter_node(state: AgentState) -> AgentState:
    letter = state.get("cover_letter")
    profile = state.get("structured_profile")
    jd = state.get("structured_jd")
    match = state.get("job_match")
    request = (state.get("letter_revision_request") or "").strip()
    if letter is None or profile is None or jd is None or match is None or not request:
        return {}

    user_text = (
        f"=== JOB DESCRIPTION ===\n{format_jd(jd)}\n\n"
        f"=== CANDIDATE PROFILE ===\n{format_profile(profile, only_ids=set(letter.source_ids))}\n\n"
        f"=== NEVER CLAIM ===\n{format_missing(match) or 'Nothing.'}\n\n"
        f"=== CURRENT LETTER ===\n{format_letter_body(letter)}\n\n"
        f"=== REQUEST ===\n{request}"
    )
    revision = extract_structured("revise_letter", REVISE_COVER_LETTER_SYSTEM_PROMPT, user_text, CoverLetterRevision)
    return {"cover_letter": apply_letter_revision(letter, revision), "letter_revision": revision}


def mention_names(profile: StructuredProfile) -> list[tuple[str, str]]:
    """(id, a name a letter would use for it): each project as written and as a title, each experience's employer."""
    names = []
    for p in profile.projects:
        names += [(p.id, p.name.strip()), (p.id, _pretty_project_name(p.name))]
    names += [(e.id, e.organization.strip()) for e in profile.experience]
    return names


def unpicked_mentions(letter: CoverLetter, profile: StructuredProfile) -> list[str]:
    """Projects and employers the letter names although it wasn't written from them, for a warning."""
    allowed = set(letter.source_ids)
    allowed_names = {name.lower() for item_id, name in mention_names(profile) if item_id in allowed}
    body = " ".join(letter.paragraphs).lower()
    return list(dict.fromkeys(
        name for item_id, name in mention_names(profile)
        if item_id not in allowed and len(name) >= 4 and name.lower() not in allowed_names and name.lower() in body
    ))
