"""How a job match ("Job fit") and a gap plan ("Suggestions") are shown."""
import streamlit as st

from jobfit.models import CourseSuggestion, GapPlan, JobMatch, StructuredJD
from jobfit.ui.common import md

RELEVANCE_LABELS = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🟠 Low", "none": "⚪ None"}
EFFORT_LABELS = {"hours": "⏱ hours", "days": "📅 days", "weeks": "🗓 weeks", "months": "📆 months"}
EFFORT_COLOURS = {"hours": "green", "days": "green", "weeks": "orange", "months": "red"}
ITEM_TYPES = {"proj": "Project", "exp": "Experience", "cert": "Certification", "course": "Course"}
IMPORTANCE = {  # heading, badge colour
    "required": ("Required", "red"),
    "preferred": ("Nice to have", "orange"),
    "duty": ("From the duties and tech stack", "gray"),
}
IMPORTANCE_RANK = {level: n for n, level in enumerate(IMPORTANCE)}


def render_job_match(match: JobMatch, jd: StructuredJD, picks: dict[str, list[str]]) -> None:
    """picks: the item ids each document is written from ("cv", "letter"), shown as "Used in"."""
    missing_by = {level: [m for m in match.missing if m.importance == level] for level in IMPORTANCE}
    strong = sum(i.relevance == "high" for i in match.items)

    with st.container(horizontal=True):
        st.metric("Strong matches", f"{strong} of {len(match.items)}", border=True,
                  help="Your projects, experience, courses and certifications that directly fit this job.")
        st.metric("Matching skills", len(match.relevant_skills), border=True)
        st.metric("Missing: required", len(missing_by["required"]), border=True)
        st.metric("Missing: nice to have", len(missing_by["preferred"]), border=True)

    items_col, side_col = st.columns([3, 2], gap="large")
    with items_col:
        st.markdown("##### Your items, ranked for this job")
        st.caption("Only high and medium items are used: the best of each kind on the CV (it has limited "
                   "room), and all of them in the cover letter.")
        st.dataframe(
            [
                {
                    "Item": i.name,
                    "Type": ITEM_TYPES.get(i.id.split("_")[0], ""),
                    "Relevance": RELEVANCE_LABELS[i.relevance],
                    "Used in": " · ".join(label for doc, label in (("cv", "CV"), ("letter", "Letter"))
                                          if i.id in picks[doc]),
                    "Why": i.reason,
                }
                for i in match.items
            ],
            hide_index=True,
            width="stretch",
            column_config={"Why": st.column_config.TextColumn(width="large")},
        )
    with side_col:
        st.markdown("##### Skills that match")
        if match.relevant_skills:
            st.markdown(" ".join(f":blue-badge[{md(s)}]" for s in match.relevant_skills))
        else:
            st.caption("None of your skills match this job.")

        st.markdown("##### What's missing")
        if not match.missing:
            st.success("Nothing. Your profile covers every requirement.")
        for level, (heading, colour) in IMPORTANCE.items():
            if missing_by[level]:
                st.markdown(f":{colour}-badge[{heading}]")
                st.markdown("\n".join(f"- **{md(m.requirement)}**: {md(m.note)}" for m in missing_by[level]))

    with st.expander("What the job asks for"):
        for heading, values in (("Required", jd.requirements), ("Nice to have", jd.preferred),
                                ("Responsibilities", jd.responsibilities)):
            if values:
                st.markdown(f"**{heading}**\n" + "\n".join(f"- {md(v)}" for v in values))
        if jd.tech_stack:
            st.markdown("**Tech stack**  \n" + " · ".join(md(t) for t in jd.tech_stack))


def render_gap_plan(plan: GapPlan, match: JobMatch) -> None:
    """Each suggestion is a card: what, time, cost and coverage at a glance; the details stay folded."""
    if not (plan.project_add_ons or plan.new_projects or plan.courses):
        if match.missing:
            st.info("No project or course would close what's missing for this job (see **Job fit**).")
        else:
            st.success("Nothing to add. Your profile already covers this job's requirements.")
        return

    importance = {m.requirement: m.importance for m in match.missing}
    covered = {gap for item in plan.project_add_ons + plan.new_projects + plan.courses for gap in item.covers}
    required = [m.requirement for m in match.missing if m.importance == "required"]
    with st.container(horizontal=True):
        st.metric("Project improvements", len(plan.project_add_ons), border=True)
        st.metric("New projects", len(plan.new_projects), border=True)
        st.metric("Courses", len(plan.courses), border=True)
        st.metric("Required gaps covered", f"{len(covered.intersection(required))} of {len(required)}", border=True,
                  help="The rest can't be closed with a project or a course (e.g. citizenship, a clearance, "
                       "where you live), or got no good suggestion. See **Job fit** for the full list.")

    build_col, learn_col = st.columns([3, 2], gap="large")
    with build_col:
        st.markdown("##### Build")
        for a in plan.project_add_ons:
            project_card(":material/build:", a.title, (a.project_name, ":material/folder:", "gray"), a.effort,
                         a.covers, importance, a.why_it_fits, a.steps, a.cv_bullet_preview)
        for n in plan.new_projects:
            details = n.description + (f" Tech stack: {', '.join(n.tech_stack)}." if n.tech_stack else "")
            project_card(":material/add_box:", n.title, ("New project", ":material/add:", "violet"), n.effort,
                         n.covers, importance, details, n.steps, "")
        if not (plan.project_add_ons or plan.new_projects):
            st.caption("No project fits these gaps well.")
    with learn_col:
        st.markdown("##### Learn")
        for c in plan.courses:
            course_card(c, importance)
        if plan.courses:
            st.caption("Found with a web search. Check the price and content on the page before you sign up.")
        else:
            st.caption("No course or certification fits these gaps well.")


def badge_row(effort: str, covers: list[str], *badges: tuple[str, str, str]) -> None:
    """badges: (label, icon, colour), shown before the effort and the gaps covered (listed on hover)."""
    with st.container(horizontal=True, gap="small"):
        for label, icon, colour in badges:
            st.badge(label, icon=icon, color=colour)
        st.badge(EFFORT_LABELS[effort], color=EFFORT_COLOURS[effort])
        st.badge(f"Covers {len(covers)} gap{'' if len(covers) == 1 else 's'}", icon=":material/check:",
                 color="blue", help="\n".join(f"- {md(c)}" for c in covers))


def gap_badges(covers: list[str], importance: dict[str, str]) -> None:
    """The gaps a suggestion covers, required first, coloured as on Job fit."""
    ordered = sorted(covers, key=lambda c: IMPORTANCE_RANK.get(importance.get(c, "duty"), 2))
    st.markdown(" ".join(f":{IMPORTANCE[importance.get(c, 'duty')][1]}-badge[{md(c)}]" for c in ordered))


def project_card(icon: str, title: str, label: tuple[str, str, str], effort: str, covers: list[str],
                 importance: dict[str, str], why: str, steps: list[str], cv_bullet: str) -> None:
    with st.container(border=True):
        st.markdown(f"{icon} **{md(title)}**")
        badge_row(effort, covers, label)
        with st.expander("Steps and CV bullet" if cv_bullet else "Steps", type="compact"):
            st.markdown(md(why))
            st.markdown("\n".join(f"{n}. {md(step)}" for n, step in enumerate(steps, start=1)))
            st.caption("Gaps it covers")
            gap_badges(covers, importance)
            if cv_bullet:
                st.caption("CV bullet once it's done")
                st.code(cv_bullet, language=None, wrap_lines=True)


def course_card(c: CourseSuggestion, importance: dict[str, str]) -> None:
    certification = c.kind == "certification"
    with st.container(border=True):
        with st.container(horizontal=True, vertical_alignment="center"):
            icon = ":material/workspace_premium:" if certification else ":material/school:"
            st.markdown(f"{icon} **{md(c.title)}**", width="stretch")
            if c.url:
                st.link_button("Open", c.url, icon=":material/open_in_new:", type="tertiary",
                               help=f"{'Certification' if certification else 'Course'} page")
        free = c.cost.strip().lower().startswith("free")
        badge_row(c.effort, c.covers, (c.provider, None, "gray"),
                  (c.cost, ":material/payments:", "green" if free else "gray"))
        with st.expander(f"Why this {'certification' if certification else 'course'}", type="compact"):
            st.markdown(md(c.why))
            gap_badges(c.covers, importance)
