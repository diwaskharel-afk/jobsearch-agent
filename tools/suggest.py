"""Build the Suggestions of a saved run log with the real LLM, without running the rest of the pipeline.

    streamlit run tools/suggest.py                                  # pick a run in the sidebar
    streamlit run tools/suggest.py -- TestRunJson/20261016_094233_Member_of_Technical_Staff.json

Dev tool (needs the API key in .env): loads a run's profile, job and match and runs the app's own
recommend_gaps_node on them, so parsing and matching are reused from the log and each click costs
only the two suggestion calls (projects, and courses with web search). A run that already has
suggestions shows them without any call. After each click it shows the result as the app draws it,
what the model saw and returned before code filtered it, and a few automatic checks.
"""
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent.parent  # the repo root
sys.path.insert(0, str(PROJECT_DIR))  # so `jobfit` imports when this file is run directly

from jobfit import nodes
from jobfit.formatting import gap_ids
from jobfit.llm import TASK_MODELS, model_for
from jobfit.models import GapPlan, JobMatch, StructuredJD, StructuredProfile
from jobfit.ui.common import md, safe_filename
from jobfit.ui.job_results import render_gap_plan

RUN_DIRS = (PROJECT_DIR / "TestRunJson", PROJECT_DIR)
# Gaps no project or course closes; a suggestion that covers one is a prompt failure.
UNCLOSABLE = re.compile(r"citizen|clearance|work permit|visa|degree|years of|relocat|hybrid|on-?site|"
                        r"based in|live in", re.IGNORECASE)
ID_IN_TEXT = re.compile(r"\b(gap|proj|exp|course|cert)_\d+\b")


def saved_runs() -> list[Path]:
    runs = [run for folder in RUN_DIRS if folder.is_dir() for run in folder.glob("[0-9]*_*.json")]
    return sorted(runs, key=lambda run: run.name, reverse=True)


def load_run(path: Path) -> dict:
    run = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in ("structured_profile", "structured_jd", "job_match") if not run.get(key)]
    if missing:
        raise ValueError(f"{path.name} has no {', '.join(missing)}, so there's nothing to suggest from.")
    return run


def load_uploaded(upload) -> dict:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / upload.name
        path.write_bytes(upload.getvalue())
        return load_run(path)


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


# --- One build, recorded ------------------------------------------------------------
# recommend_gaps_node runs as is; nodes.extract_structured is wrapped only for the call, so the
# report can show both LLM calls: the text they saw and what they returned before code filtered it.

def build(run: dict) -> None:
    calls = []
    real_llm = nodes.extract_structured

    def recording_llm(task, system_prompt, user_text, schema, **kwargs):
        result = real_llm(task, system_prompt, user_text, schema, **kwargs)
        calls.append({"task": task, "model": model_for(task), "user_text": user_text, "result": result.model_dump()})
        return result

    state = {"structured_profile": StructuredProfile.model_validate(run["structured_profile"]),
             "structured_jd": StructuredJD.model_validate(run["structured_jd"]),
             "job_match": JobMatch.model_validate(run["job_match"])}
    nodes.extract_structured = recording_llm
    start = time.perf_counter()
    try:
        plan = nodes.recommend_gaps_node(state).get("gap_plan", GapPlan())
    finally:
        nodes.extract_structured = real_llm
    calls.sort(key=lambda call: call["task"])  # the two calls finish in any order
    st.session_state["plan"] = plan.model_dump()
    st.session_state["reports"].append({
        "seconds": round(time.perf_counter() - start, 1), "calls": calls, "plan": plan.model_dump(),
        "checks": run_checks(plan, calls, state["structured_profile"], state["job_match"]),
    })


def run_checks(plan: GapPlan, calls: list[dict], profile: StructuredProfile,
               match: JobMatch) -> list[tuple[bool | None, str]]:
    tasks = sorted(call["task"] for call in calls)
    if not match.missing:
        return [(not calls, f"No gaps, so no LLM calls: {tasks}")]
    checks = [(tasks == ["courses", "gaps"], f"One projects call and one course search: {tasks}")]
    raw = {call["task"]: call["result"] for call in calls}
    raw_projects, raw_courses = raw.get("gaps", {}), raw.get("courses", {})

    # How much the model gave against what was kept (code caps and drops what covers no real gap).
    for label, given, kept, limit in (
            ("Project add-ons", raw_projects.get("project_add_ons", []), plan.project_add_ons, nodes.MAX_PLAN_ADD_ONS),
            ("New projects", raw_projects.get("new_projects", []), plan.new_projects, nodes.MAX_PLAN_NEW_PROJECTS),
            ("Courses", raw_courses.get("courses", []), plan.courses, nodes.MAX_PLAN_COURSES)):
        checks.append((len(given) <= limit or None,
                       f"{label}: the model gave {len(given)}, {len(kept)} kept (at most {limit})"))

    gaps = gap_ids(match)
    bad_ids = sorted({c for item in (raw_projects.get("project_add_ons", []) + raw_projects.get("new_projects", [])
                                     + raw_courses.get("courses", []))
                      for c in item["covers"] if c.strip().strip("[]") not in gaps})
    checks.append((not bad_ids, "Every covers entry is a real gap id"
                   + (f"; not real: {', '.join(bad_ids)}" if bad_ids else "")))
    project_ids = {p.id for p in profile.projects}
    bad_projects = [a["project_id"] for a in raw_projects.get("project_add_ons", [])
                    if a["project_id"].strip().strip("[]") not in project_ids]
    checks.append((not bad_projects, "Every add-on extends a real project"
                   + (f"; not real: {', '.join(bad_projects)}" if bad_projects else "")))

    unclosable = sorted({gap for item in plan.project_add_ons + plan.new_projects + plan.courses
                         for gap in item.covers if UNCLOSABLE.search(gap)})
    checks.append((not unclosable, "No suggestion claims to close citizenship, a clearance, a degree, years "
                   "or location" + (f"; found: {'; '.join(unclosable)}" if unclosable else "")))

    no_link = [c.title for c in plan.courses if not c.url]
    checks.append((not no_link, "Every course has a link" + (f"; none for: {'; '.join(no_link)}" if no_link else "")))
    urls = [c.url for c in plan.courses if c.url]
    checks.append((len(urls) == len(set(urls)), "No two courses share a link"))
    taken = [norm(c.name) for c in profile.courses] + [norm(c.name) for c in profile.certifications]
    repeats = [c.title for c in plan.courses
               if any(t and (t in norm(c.title) or norm(c.title) in t) for t in taken)]
    checks.append((not repeats, "No course the profile already lists"
                   + (f"; repeats: {'; '.join(repeats)}" if repeats else "")))

    texts = [a.title for a in plan.project_add_ons] + [n.title for n in plan.new_projects]
    long_titles = [t for t in texts if len(t.split()) > 8]
    checks.append((not long_titles or None, "Project titles have at most 8 words"
                   + (f"; longer: {'; '.join(long_titles)}" if long_titles else "")))
    shown = (texts + [a.why_it_fits for a in plan.project_add_ons] + [n.description for n in plan.new_projects]
             + [s for item in plan.project_add_ons + plan.new_projects for s in item.steps]
             + [a.cv_bullet_preview for a in plan.project_add_ons] + [c.why for c in plan.courses])
    leaked = sorted({m.group(0) for text in shown for m in ID_IN_TEXT.finditer(text)})
    checks.append((not leaked, "No ids like gap_3 in the shown text" + (f"; found: {', '.join(leaked)}" if leaked else "")))
    return checks


def render_report(report: dict) -> None:
    icons = {True: "✅", False: "❌", None: "⚠️"}
    st.markdown("\n".join(f"- {icons[ok]} {md(what)}" for ok, what in report["checks"]))
    st.caption(f"{report['seconds']} s · " + ", ".join(f"{c['task']}: {c['model']}" for c in report["calls"]))
    if report["calls"]:
        with st.expander("What the model saw (same text for both calls)"):
            st.code(report["calls"][0]["user_text"], language=None)
    for call in report["calls"]:
        with st.expander(f"What the model returned ({call['task']}), before code filtered it"):
            st.json(call["result"])


st.set_page_config(page_title="Suggestions test", page_icon="💡", layout="wide")
st.title("Suggestions test")

runs = saved_runs()
cli_run = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if cli_run and cli_run not in runs:
    runs.insert(0, cli_run)

with st.sidebar:
    st.header("Run log")
    upload = st.file_uploader("Upload a run (JSON)", type="json")
    run_path = st.selectbox(
        "…or pick a saved run", runs, index=runs.index(cli_run) if cli_run else 0,
        format_func=lambda run: run.name if run.parent in RUN_DIRS else str(run), disabled=upload is not None,
    ) if runs else None
    reload = st.button("Start over from the saved run", help="Drops the suggestions built here.")
    st.caption(f"Projects model: {model_for('gaps')} (effort {TASK_MODELS['gaps'][1]})  \n"
               f"Course search model: {model_for('courses')} (effort {TASK_MODELS['courses'][1]})")

if upload is None and run_path is None:
    st.info("No saved runs in TestRunJson/ or the project folder; upload one in the sidebar.")
    st.stop()

try:
    run = load_uploaded(upload) if upload is not None else load_run(run_path)
except Exception as exc:
    st.error("This run couldn't be read:")
    st.code(str(exc))
    st.stop()

run_key = f"upload:{upload.name}:{upload.size}" if upload is not None else str(run_path)
if reload or st.session_state.get("loaded_run") != run_key:
    st.session_state.update(loaded_run=run_key, reports=[], plan=run.get("gap_plan"))

jd = run["structured_jd"]
match = JobMatch.model_validate(run["job_match"])
with st.sidebar:
    with st.expander(f"Gaps in the saved match ({len(match.missing)})"):
        st.markdown("\n".join(f"- *{m.importance}*: {md(m.requirement)}" for m in match.missing) or "Nothing.")

st.caption(f"Run: {upload.name if upload is not None else run_path.name}  ·  Job: "
           f"{md(jd.get('title')) or '?'}" + (f" at {md(jd['company'])}" if jd.get("company") else ""))

with st.container(horizontal=True, vertical_alignment="center"):
    st.markdown("#### Suggestions", width="stretch")
    clicked = st.button("Get suggestions" if not st.session_state["plan"] else "Get new suggestions",
                        type="primary", icon=":material/lightbulb:",
                        help="Two LLM calls: projects, and courses with web search. No rematching.")
if clicked:
    try:
        with st.spinner(f"Finding suggestions with {model_for('gaps')} and searching for courses with "
                        f"{model_for('courses')}..."):
            build(run)
    except Exception as exc:
        st.error("Building the suggestions failed:")
        st.code(str(exc))
    else:
        st.rerun()

reports = st.session_state["reports"]
if st.session_state["plan"]:
    if not reports:
        st.caption("Saved in the run; no LLM call made.")
    try:
        render_gap_plan(GapPlan.model_validate(st.session_state["plan"]), has_gaps=bool(match.missing))
    except Exception as exc:  # e.g. a run saved before the Suggestions layout
        st.warning("The run's saved suggestions couldn't be shown; get new ones.")
        st.code(str(exc))
else:
    st.info("This run has no suggestions yet. Click **Get suggestions**.")

if reports:  # newest first; tabs, since the suggestion boxes are expanders and can't sit in one
    st.divider()
    st.subheader("Report")
    numbered = list(reversed(list(enumerate(reports, start=1))))
    tabs = st.tabs([f"Build {n}{' (latest)' if n == len(reports) else ''} · {r['seconds']} s" for n, r in numbered])
    for tab, (number, report) in zip(tabs, numbered):
        with tab:
            if number != len(reports):  # the latest is drawn above
                render_gap_plan(GapPlan.model_validate(report["plan"]), has_gaps=bool(match.missing))
            render_report(report)

if st.session_state["plan"]:
    st.divider()
    new_run = {  # same shape as the app's run download, with these suggestions
        **run, "saved_at": datetime.now().isoformat(timespec="seconds"),
        "models": {task: model_for(task) for task in TASK_MODELS}, "gap_plan": st.session_state["plan"],
    }
    st.download_button("Download run (JSON)", data=json.dumps(new_run, indent=2, ensure_ascii=False),
                       file_name=f"{datetime.now():%Y%m%d_%H%M%S}_{safe_filename(jd.get('title'), 'run')}.json",
                       mime="application/json")
