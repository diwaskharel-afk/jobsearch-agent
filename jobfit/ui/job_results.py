"""How a job match and a gap plan are shown."""
import streamlit as st

from jobfit.models import GapPlan, JobMatch

RELEVANCE_LABELS = {"high": "🟢 high", "medium": "🟡 medium", "low": "🟠 low", "none": "⚪ none"}
EFFORT_LABELS = {"hours": "⏱ hours", "days": "📅 days", "weeks": "🗓 weeks", "months": "📆 months"}
ITEM_TYPES = {"proj": "project", "exp": "experience", "cert": "certification", "course": "course"}


def render_job_match(match: JobMatch) -> None:
    st.subheader("Your profile vs this job")

    st.markdown("**Your items, ranked for this job**")
    st.dataframe(
        [
            {
                "item": i.name,
                "type": ITEM_TYPES.get(i.id.split("_")[0], ""),
                "relevance": RELEVANCE_LABELS[i.relevance],
                "why": i.reason,
            }
            for i in match.items
        ],
        hide_index=True,
        width="stretch",
    )

    st.markdown("**Relevant skills**")
    st.write(", ".join(match.relevant_skills) or "None of your skills match this job.")

    st.markdown("**Missing — not covered by your items or skills**")
    if not match.missing:
        st.write("Nothing missing — every requirement is covered.")
    for m in sorted(match.missing, key=lambda m: m.importance != "required"):
        st.markdown(f"- **{m.requirement}** ({m.importance}) — {m.note}")


def render_gap_plan(plan: GapPlan) -> None:
    st.subheader("How to close your gaps")

    if not any([plan.maybe_already_have, plan.project_add_ons, plan.new_projects,
                plan.learning, plan.not_fixable_now, plan.uncovered]):
        st.write("Nothing to close — you already cover this job's requirements.")
        return

    if plan.maybe_already_have:
        st.markdown("**Maybe you already have these — add them to your profile**")
        for hint in plan.maybe_already_have:
            st.markdown(f"- {hint}")

    if plan.project_add_ons:
        st.markdown("**Extend your existing projects**")
        for a in plan.project_add_ons:
            with st.expander(f"{a.project_name}: {a.title} ({EFFORT_LABELS[a.effort]})"):
                st.markdown(f"**Covers:** {', '.join(a.covers)}")
                st.markdown(f"**Why it fits:** {a.why_it_fits}")
                st.markdown("\n".join(f"{n}. {step}" for n, step in enumerate(a.steps, start=1)))
                st.markdown(f"**CV bullet once it's done:** _{a.cv_bullet_preview}_")

    if plan.new_projects:
        st.markdown("**New projects**")
        for n in plan.new_projects:
            with st.expander(f"{n.title} ({EFFORT_LABELS[n.effort]})"):
                st.markdown(f"**Covers:** {', '.join(n.covers)}")
                st.write(n.description)
                if n.tech_stack:
                    st.markdown(f"**Tech stack:** {', '.join(n.tech_stack)}")
                st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(n.steps, start=1)))

    if plan.learning:
        st.markdown("**Courses, certifications & docs**")
        for l in plan.learning:
            st.markdown(f"- **{l.topic}** ({l.kind}, {EFFORT_LABELS[l.effort]}) — {l.suggestion}. "
                        f"_Covers: {', '.join(l.covers)}_")

    if plan.not_fixable_now:
        st.markdown("**Can't close these quickly — address them instead**")
        for n in plan.not_fixable_now:
            st.markdown(f"- **{n.requirement}** — {n.how_to_address}")

    if plan.uncovered:
        st.markdown("**No suggestion for**")
        st.write(", ".join(plan.uncovered))
