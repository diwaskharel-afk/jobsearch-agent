from model import DatedRange, FinalCV, JobMatch, MissingRequirement, StructuredJD, StructuredProfile


def format_month(year_month: str | None) -> str:
    """"2024-08" -> "08.2024"; "" for no date."""
    if not year_month:
        return ""
    year, month = year_month.split("-")
    return f"{month}.{year}"


def format_range(entry: DatedRange) -> str:
    """"08.2024 – 06.2026", or "08.2024 – Present" while ongoing."""
    return f"{format_month(entry.start)} – {format_month(entry.end) if entry.end else 'Present'}"


def recency_key(entry: DatedRange) -> tuple[str, str]:
    """Sort key for newest first (with reverse=True): end date, ongoing on top, then start date."""
    return entry.end or "9999-99", entry.start


def _section(heading: str, items: list[str]) -> list[str]:
    return [f"\n{heading}:"] + [f"- {i}" for i in items] if items else []


def format_jd(jd: StructuredJD) -> str:
    lines = [f"Title: {jd.title}"]
    if jd.company:
        lines.append(f"Company: {jd.company}")
    if jd.seniority:
        lines.append(f"Seniority: {jd.seniority}")
    lines += _section("Required", jd.requirements)
    lines += _section("Preferred", jd.preferred)
    lines += _section("Responsibilities", jd.responsibilities)
    if jd.tech_stack:
        lines.append(f"\nTech stack: {', '.join(jd.tech_stack)}")
    return "\n".join(lines)


def item_names(profile: StructuredProfile) -> dict[str, str]:
    """id -> display name for every project, experience, certification and course."""
    names = {p.id: p.name for p in profile.projects}
    names |= {e.id: f"{e.title} at {e.organization}" for e in profile.experience}
    names |= {c.id: c.name + (f" ({c.issuer})" if c.issuer else "") for c in profile.certifications}
    names |= {c.id: c.name + (f" — {c.provider}" if c.provider else "") for c in profile.courses}
    return names


def format_profile(profile: StructuredProfile, only_ids: set[str] | None = None) -> str:
    """The profile as prompt text. only_ids limits the projects, experience, courses and
    certifications to those ids (None = all); education, skills and languages are always shown."""
    def shown(items: list) -> list:
        return [i for i in items if only_ids is None or i.id in only_ids]

    sections = []

    for p in shown(profile.projects):
        lines = [f"[{p.id}] Project: {p.name}"]
        body = p.bullets or ([p.description] if p.description.strip() else [])
        lines += [f"  - {b}" for b in body]
        sections.append("\n".join(lines))

    for e in shown(profile.experience):
        header = f"[{e.id}] Experience: {e.title} at {e.organization}"
        lines = [f"{header} ({format_range(e)})"]
        lines += [f"  - {b}" for b in (e.bullets or e.responsibilities)]
        sections.append("\n".join(lines))

    for c in shown(profile.courses):
        header = f"[{c.id}] Course: {c.name}"
        if c.provider:
            header += f" — {c.provider}"
        if c.date:
            header += f" (completed {format_month(c.date)})"
        lines = [header]
        if c.description:
            lines.append(f"  {c.description}")
        sections.append("\n".join(lines))

    for c in shown(profile.certifications):
        header = f"[{c.id}] Certification: {c.name}"
        if c.issuer:
            header += f" ({c.issuer})"
        if c.date:
            header += f", {format_month(c.date)}"
        sections.append(header)

    # No ids: education is context (e.g. for degree requirements), never a ranked item.
    for edu in profile.education:
        line = f"Education: {edu.degree}"
        if edu.institution:
            line += f" — {edu.institution}"
        line += f" ({format_range(edu)})"
        if edu.expected_graduation:
            line += f", expected graduation {format_month(edu.expected_graduation)}"
        if edu.description:
            line += f"\n  {edu.description}"
        sections.append(line)

    if profile.skills:
        sections.append(f"Skills: {', '.join(profile.skills)}")
    if profile.languages:
        sections.append(f"Languages: {', '.join(profile.languages)}")

    return "\n\n".join(sections)


def format_job_match(match: JobMatch) -> str:
    lines = ["Profile items ranked by relevance:"]
    lines += [f"- [{i.id}] {i.name}: {i.relevance} — {i.reason}" for i in match.items]
    if match.relevant_skills:
        lines.append(f"\nRelevant skills: {', '.join(match.relevant_skills)}")
    if match.missing:
        lines.append("\nNot in the profile — never claim these:")
        lines += [f"- {m.requirement} ({m.importance})" for m in match.missing]
    return "\n".join(lines)


def format_missing(match: JobMatch) -> str:
    return "\n".join(f"- {m.requirement} ({m.importance})" for m in match.missing)


def format_cv_for_revision(cv: FinalCV) -> str:
    """The parts of the CV a revision can change, with item ids."""
    lines = [f"Objective: {cv.objective}", f"Skills: {', '.join(cv.skills)}"]
    for p in cv.projects:
        lines += [f"\n[{p.id}] Project: {p.name}", f"  Tech stack: {', '.join(p.tech_stack)}"]
        lines += [f"  - {b}" for b in p.bullets]
    for e in cv.experience:
        lines.append(f"\n[{e.id}] Experience: {e.title} at {e.organization} ({e.duration})")
        lines += [f"  - {b}" for b in e.bullets]
    return "\n".join(lines)


def gap_ids(match: JobMatch) -> dict[str, MissingRequirement]:
    """gap_1, gap_2, ... -> missing requirement, in JobMatch order."""
    return {f"gap_{n}": m for n, m in enumerate(match.missing, start=1)}


def format_gaps(match: JobMatch) -> str:
    lines = ["Profile items ranked by relevance:"]
    lines += [f"- [{i.id}] {i.name}: {i.relevance} — {i.reason}" for i in match.items]
    lines.append("\nMissing requirements:")
    lines += [f"- [{gid}] {m.requirement} ({m.importance}) — {m.note}" for gid, m in gap_ids(match).items()]
    return "\n".join(lines)
