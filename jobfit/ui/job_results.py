"""How a job match ("Job fit") and a gap plan ("Skill-gap plan") are shown."""
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


def render_gap_plan(plan: GapPlan) -> None:
    if not any([plan.maybe_already_have, plan.project_add_ons, plan.new_projects,
                plan.learning, plan.not_fixable_now, plan.uncovered]):
        st.success("Nothing to close. You already cover this job's requirements.")
        return

    if plan.maybe_already_have:
        st.markdown("##### You may already have these: add them to your profile")
        st.markdown("\n".join(f"- {md(hint)}" for hint in plan.maybe_already_have))

    if plan.project_add_ons:
        st.markdown("##### Extend your existing projects")
        for a in plan.project_add_ons:
            with st.expander(f"{a.project_name}: {a.title} ({EFFORT_LABELS[a.effort]})"):
                st.markdown(f"**Covers:** {md(', '.join(a.covers))}")
                st.markdown(f"**Why it fits:** {md(a.why_it_fits)}")
                st.markdown("\n".join(f"{n}. {md(step)}" for n, step in enumerate(a.steps, start=1)))
                st.markdown(f"**CV bullet once it's done:** _{md(a.cv_bullet_preview)}_")

    if plan.new_projects:
        st.markdown("##### New projects")
        for n in plan.new_projects:
            with st.expander(f"{n.title} ({EFFORT_LABELS[n.effort]})"):
                st.markdown(f"**Covers:** {md(', '.join(n.covers))}")
                st.write(n.description)
                if n.tech_stack:
                    st.markdown(f"**Tech stack:** {md(', '.join(n.tech_stack))}")
                st.markdown("\n".join(f"{i}. {md(step)}" for i, step in enumerate(n.steps, start=1)))

    if plan.learning:
        st.markdown("##### Courses, certifications and docs")
        for l in plan.learning:
            st.markdown(f"- **{md(l.topic)}** ({l.kind}, {EFFORT_LABELS[l.effort]}): {md(l.suggestion)}. "
                        f"_Covers: {md(', '.join(l.covers))}_")

    if plan.not_fixable_now:
        st.markdown("##### Can't close these quickly: address them instead")
        st.markdown("\n".join(f"- **{md(n.requirement)}**: {md(n.how_to_address)}" for n in plan.not_fixable_now))

    if plan.uncovered:
        st.markdown("##### No suggestion for")
        st.write(", ".join(plan.uncovered))
