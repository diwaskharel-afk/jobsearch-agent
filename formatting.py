from model import JobMatch, MissingRequirement, StructuredJD, StructuredProfile


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


def format_profile(profile: StructuredProfile) -> str:
    sections = []

    for p in profile.projects:
        lines = [f"[{p.id}] Project: {p.name}"]
        body = p.bullets or ([p.description] if p.description.strip() else [])
        lines += [f"  - {b}" for b in body]
        sections.append("\n".join(lines))

    for e in profile.experience:
        header = f"[{e.id}] Experience: {e.title} at {e.organization}"
        lines = [header + (f" ({e.duration})" if e.duration else "")]
        lines += [f"  - {b}" for b in (e.bullets or e.responsibilities)]
        sections.append("\n".join(lines))

    for c in profile.courses:
        header = f"[{c.id}] Course: {c.name}"
        if c.provider:
            header += f" — {c.provider}"
        if c.date:
            header += f" ({c.date})"
        lines = [header]
        if c.description:
            lines.append(f"  {c.description}")
        sections.append("\n".join(lines))

    for c in profile.certifications:
        header = f"[{c.id}] Certification: {c.name}"
        if c.issuer:
            header += f" ({c.issuer})"
        sections.append(header)

    # No ids: education is context (e.g. for degree requirements), never a ranked item.
    for edu in profile.education:
        line = f"Education: {edu.degree}"
        if edu.institution:
            line += f" — {edu.institution}"
        if edu.duration:
            line += f" ({edu.duration})"
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


def gap_ids(match: JobMatch) -> dict[str, MissingRequirement]:
    """gap_1, gap_2, ... -> missing requirement, in JobMatch order."""
    return {f"gap_{n}": m for n, m in enumerate(match.missing, start=1)}


def format_gaps(match: JobMatch) -> str:
    lines = ["Profile items ranked by relevance:"]
    lines += [f"- [{i.id}] {i.name}: {i.relevance} — {i.reason}" for i in match.items]
    lines.append("\nMissing requirements:")
    lines += [f"- [{gid}] {m.requirement} ({m.importance}) — {m.note}" for gid, m in gap_ids(match).items()]
    return "\n".join(lines)
