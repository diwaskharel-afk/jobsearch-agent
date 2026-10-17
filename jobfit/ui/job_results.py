"""How a job match ("Job fit") and a gap plan ("Suggestions") are shown."""
import streamlit as st

from jobfit.models import GapPlan, JobMatch, StructuredJD
from jobfit.ui.common import md

RELEVANCE_LABELS = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🟠 Low", "none": "⚪ None"}
EFFORT_LABELS = {"hours": "⏱ hours", "days": "📅 days", "weeks": "🗓 weeks", "months": "📆 months"}
ITEM_TYPES = {"proj": "Project", "exp": "Experience", "cert": "Certification", "course": "Course"}
IMPORTANCE = {  # heading, badge colour
    "required": ("Required", "red"),
    "preferred": ("Nice to have", "orange"),
    "duty": ("From the duties and tech stack", "gray"),
}


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


def render_gap_plan(plan: GapPlan, has_gaps: bool) -> None:
    """Each suggestion is a one-line box; its details show only when it's opened."""
    if not (plan.project_add_ons or plan.new_projects or plan.courses):
        if has_gaps:
            st.info("No project or course would close what's missing for this job (see **Job fit**).")
        else:
            st.success("Nothing to add. Your profile already covers this job's requirements.")
        return

    if plan.project_add_ons:
        st.markdown("##### Improve your projects")
        for a in plan.project_add_ons:
            with st.expander(f"{md(a.project_name)}: {md(a.title)} · {EFFORT_LABELS[a.effort]}",
                             icon=":material/build:"):
                st.markdown(f"**Covers:** {md(', '.join(a.covers))}")
                st.markdown(md(a.why_it_fits))
                st.markdown("\n".join(f"{n}. {md(step)}" for n, step in enumerate(a.steps, start=1)))
                st.markdown(f"**CV bullet once it's done:** _{md(a.cv_bullet_preview)}_")

    if plan.new_projects:
        st.markdown("##### New small project")
        for n in plan.new_projects:
            with st.expander(f"{md(n.title)} · {EFFORT_LABELS[n.effort]}", icon=":material/add_box:"):
                st.markdown(f"**Covers:** {md(', '.join(n.covers))}")
                st.markdown(md(n.description))
                if n.tech_stack:
                    st.markdown(f"**Tech stack:** {md(', '.join(n.tech_stack))}")
                st.markdown("\n".join(f"{i}. {md(step)}" for i, step in enumerate(n.steps, start=1)))

    if plan.courses:
        st.markdown("##### Courses and certifications")
        for c in plan.courses:
            icon = ":material/workspace_premium:" if c.kind == "certification" else ":material/school:"
            with st.expander(f"{md(c.title)} ({md(c.provider)}) · {md(c.cost)} · {EFFORT_LABELS[c.effort]}",
                             icon=icon):
                st.markdown(f"**Covers:** {md(', '.join(c.covers))}")
                st.markdown(md(c.why))
                if c.url:
                    st.link_button("Open course page" if c.kind == "course" else "Open certification page",
                                   c.url, icon=":material/open_in_new:")
        st.caption("Found with a web search. Check the price and content on the page before you sign up.")
