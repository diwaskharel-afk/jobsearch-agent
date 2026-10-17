"""Revise the CV of a saved run log, or swap its items, with the real LLM, without running the rest
of the pipeline.

    streamlit run tools/revise_cv.py                                  # pick a run in the sidebar
    streamlit run tools/revise_cv.py -- TestRunJson/20261016_094233_Member_of_Technical_Staff.json

Dev tool (needs the API key in .env): loads a run's profile, job, match and final_cv into
the app's session state and revises it with the app's own revise_cv and swap_item, so every
request goes through the real graph and model, while parsing, matching and CV generation are
reused from the log. After each revision or swap it shows what the model saw and returned, a
before/after diff and a few automatic checks. The app's Edit button and swap menus on the preview
are here too, with the same report, so you can check a hand edit makes no LLM call.
"""
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent.parent  # the repo root
sys.path.insert(0, str(PROJECT_DIR))  # so `jobfit` imports when this file is run directly

from jobfit import nodes
from jobfit.formatting import format_range, recency_key
from jobfit.llm import TASK_MODELS, model_for
from jobfit.models import FinalCV, JobMatch, StructuredProfile
from jobfit.render_cv import render_cv_pdf
from jobfit.ui.common import md, safe_filename
from jobfit.ui import versions
from jobfit.ui.cv_view import DOC, REVISION_PLACEHOLDER, editable_cv, request_swap, revise_cv, swap_item, take_swap
from jobfit.ui.job_results import RELEVANCE_LABELS
from jobfit.ui.job_run import clear_job
from jobfit.ui.versions import render_revision_result
from render_run_pdf import load_final_cv

RUN_DIRS = (PROJECT_DIR / "TestRunJson", PROJECT_DIR)


def saved_runs() -> list[Path]:
    runs = [run for folder in RUN_DIRS if folder.is_dir() for run in folder.glob("[0-9]*_*.json")]
    return sorted(runs, key=lambda run: run.name, reverse=True)


def load_run(path: Path) -> tuple[dict, FinalCV]:
    """The whole log, plus its final_cv checked (and old-log fixed up) the way render_run_pdf does."""
    run = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in ("structured_profile", "structured_jd", "job_match") if not run.get(key)]
    if missing:
        raise ValueError(f"{path.name} has no {', '.join(missing)}, so it can't be revised.")
    return run, load_final_cv(path)


def load_uploaded(upload) -> tuple[dict, FinalCV]:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / upload.name
        path.write_bytes(upload.getvalue())
        return load_run(path)


def norm(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def backfill_ids(cv: FinalCV, profile: StructuredProfile) -> tuple[FinalCV, list[str], list[str]]:
    """Logs saved before CV items carried their profile id: find each item's entry by name
    (projects, courses) or title and organization (experience), since revisions and swaps find items by id."""
    project_ids = {norm(p.name): p.id for p in profile.projects}
    job_ids = {(norm(e.title), norm(e.organization)): e.id for e in profile.experience}
    course_ids = {norm(c.name): c.id for c in profile.courses}
    filled, unmatched = [], []

    def with_id(entry, label: str, found: str | None):
        if entry.id:
            return entry
        if not found:
            unmatched.append(label)
            return entry
        filled.append(f"{label} → {found}")
        return entry.model_copy(update={"id": found})

    cv = cv.model_copy(update={
        "projects": [with_id(p, p.name, project_ids.get(norm(p.name))) for p in cv.projects],
        "experience": [with_id(e, f"{e.title.strip()} ({e.organization.strip()})",
                               job_ids.get((norm(e.title), norm(e.organization)))) for e in cv.experience],
        "courses": [with_id(c, c.name, course_ids.get(norm(c.name))) for c in cv.courses],
    })
    return cv, filled, unmatched


def example_requests(cv: FinalCV) -> list[str]:
    """One request per rule of the revise prompt; the expected outcome is in brackets."""
    first = cv.projects[0].name if cv.projects else "my first project"
    return [
        "Don't call me junior anywhere, and keep the objective to two sentences.  [objective only]",
        f"Make the {first} bullets shorter and lead each one with the result.  [one item's bullets]",
        "Put Python first in the skills and drop any soft skills.  [skills only]",
        "Add SQL, AWS and Power BI to my skills.  [refused if they are in NEVER CLAIM]",
        f"I used SQLite to store results in {first}; add that to its bullets and tech stack.  "
        "[done, with a note to add it to the profile]",
        f"Remove {first} and put my other projects on the CV instead.  [not_done, pointing to the swap button]",
        "Change my name to D. Kharel and the internship dates to 2024.  [not_done]",
    ]


# --- One revision, recorded ---------------------------------------------------------
# The app's revise_cv and manual edit form run as is; nodes.extract_structured is wrapped only
# for the call, so the report can show every LLM call: its task, the text it saw and what it returned.

MANUAL = "Manual edit"  # the request the app's manual edit form records


def record(request: str, action, check=None) -> bool:
    """Run action() (a revision, a swap or the manual edit form) and add its report; True if a report
    was added. check(before, after, calls) gives the checks; by default those for a revision or hand edit."""
    calls = []
    real_llm = nodes.extract_structured

    def recording_llm(task, system_prompt, user_text, schema):
        result = real_llm(task, system_prompt, user_text, schema)
        calls.append({"task": task, "model": model_for(task), "user_text": user_text, "result": result.model_dump()})
        return result

    before = versions.current(DOC)
    nodes.extract_structured = recording_llm
    start = time.perf_counter()
    try:
        done = action()
    finally:
        nodes.extract_structured = real_llm
    if done is False:  # the manual form drawn but not saved: nothing to report
        return False
    after = versions.current(DOC)
    if check is not None:
        checks = check(before, after, calls)
    elif request == MANUAL:
        checks = manual_checks(before, after, calls)
    else:
        checks = run_checks(before, after, calls, request)
    st.session_state["reports"].append({
        "request": request, "seconds": round(time.perf_counter() - start, 1), "calls": calls,
        "before": before, "after": after, "checks": checks,
    })
    return True


def fixed_parts(cv: FinalCV) -> tuple:
    """What no revision may change: names, contact, links, dates, education and courses."""
    return (cv.name, cv.contact, cv.education, cv.courses,
            [(p.id, p.name, p.repo_url) for p in cv.projects],
            [(e.id, e.title, e.organization, e.duration) for e in cv.experience])


def added_terms(old: FinalCV, new: FinalCV) -> list[str]:
    """Skills and project tools on the new CV that the old one didn't have."""
    added = [s for s in new.skills if norm(s) not in {norm(o) for o in old.skills}]
    for old_p, new_p in zip(old.projects, new.projects):
        added += [t for t in new_p.tech_stack if norm(t) not in {norm(o) for o in old_p.tech_stack}]
    return added


def manual_checks(before: dict, after: dict, calls: list[dict]) -> list[tuple[bool | None, str]]:
    old, new = FinalCV.model_validate(before), FinalCV.model_validate(after)
    tasks = [call["task"] for call in calls]
    checks = [(not calls, f"No LLM calls: {tasks}"),
              (fixed_parts(old) == fixed_parts(new), "Names, contact, links, dates, education and courses unchanged")]
    profile = json.dumps(st.session_state["run_profile"], ensure_ascii=False).lower()
    if not_in_profile := sorted({term for term in added_terms(old, new) if term.lower() not in profile}):
        checks.append((None, f"Typed in, not in the profile: {not_in_profile} (fine if meant)"))
    return checks


def run_checks(before: dict, after: dict, calls: list[dict], request: str) -> list[tuple[bool | None, str]]:
    """(passed, what) per check; None means look at it yourself."""
    old, new = FinalCV.model_validate(before), FinalCV.model_validate(after)
    revision = calls[-1]["result"] if calls else {}
    checks = []

    tasks = [call["task"] for call in calls]
    checks.append((tasks == ["revise"], f"One LLM call, for 'revise' (parse, match and CV generation skipped): {tasks}"))

    on_cv = {p.id for p in old.projects} | {e.id for e in old.experience}
    unknown = [i["id"] for i in revision.get("items", []) if i["id"].strip().strip("[]") not in on_cv]
    checks.append((not unknown, "Every patched id is on the CV" + (f"; unknown: {unknown}" if unknown else "")))

    checks.append((fixed_parts(old) == fixed_parts(new), "Names, contact, links, dates, education and courses unchanged"))

    changed = old != new
    if revision.get("changes") and not changed:
        checks.append((False, "The model listed changes, but none reached the CV"))
    elif changed and not revision.get("changes"):
        checks.append((None, "The CV changed, but the model listed no changes"))
    else:
        checks.append((True, "The changes list matches whether the CV changed"))

    # New skills and tools must come from the profile or be stated in the request.
    source = (json.dumps(st.session_state["run_profile"], ensure_ascii=False) + " " + request).lower()
    added = added_terms(old, new)
    unsupported = sorted({term for term in added if term.lower() not in source})
    checks.append((not unsupported, "New skills and tools all appear in the profile or the request"
                   + (f"; not found: {unsupported}" if unsupported else "")))

    missing_text = " ".join(m["requirement"] for m in st.session_state["job_match"].get("missing", [])).lower()
    never_claim = sorted({term for term in added if term.lower() in missing_text})
    if never_claim:
        checks.append((None if any(t.lower() in request.lower() for t in never_claim) else False,
                       f"Added terms that are in NEVER CLAIM: {never_claim} (allowed only if the request "
                       "states them as a fact, not just asks to add them)"))
    return checks


# --- Swaps --------------------------------------------------------------------------------
# A swap is picked in a menu on the preview (as in the app) or with a scenario button; either
# leaves it pending, and it runs at the top of the page through the app's swap_item, recorded.

def swap_label(old_id: str, new_id: str) -> str:
    names = nodes.item_names(StructuredProfile.model_validate(st.session_state["run_profile"]))
    return f"Swap {names.get(old_id, old_id)} [{old_id}] → {names.get(new_id, new_id)} [{new_id}]"


def all_entries(cv: FinalCV) -> list:
    return cv.experience + cv.projects + cv.courses


def swap_checks(before: dict, after: dict, calls: list[dict], old_id: str, new_id: str) -> list[tuple[bool | None, str]]:
    """(passed, what) per check; None means look at it yourself."""
    old, new = FinalCV.model_validate(before), FinalCV.model_validate(after)
    profile = StructuredProfile.model_validate(st.session_state["run_profile"])
    match = JobMatch.model_validate(st.session_state["job_match"])
    kind = new_id.split("_")[0]
    tasks = [call["task"] for call in calls]
    checks = []

    expected = [] if kind == "course" else ["swap"]
    checks.append((tasks == expected, ("No LLM call for a course" if kind == "course" else "One LLM call, for 'swap'")
                   + f" (parse, match and CV generation skipped): {tasks}"))
    new_ids = nodes.cv_item_ids(new)
    checks.append((old_id not in new_ids and new_id in new_ids, f"{old_id} is off the CV and {new_id} is on it"))
    checks.append(((len(old.experience), len(old.projects), len(old.courses))
                   == (len(new.experience), len(new.projects), len(new.courses)), "Same number of items in each section"))
    others_before = {e.id: e for e in all_entries(old) if e.id != old_id}
    others_after = {e.id: e for e in all_entries(new) if e.id != new_id}
    checks.append((others_before == others_after, "Every other item is on the CV, word for word"))
    checks.append(((old.name, old.contact, old.education) == (new.name, new.contact, new.education),
                   "Name, contact and education unchanged"))

    entry = next((e for e in all_entries(new) if e.id == new_id), None)
    if entry is None:
        return checks
    if kind == "proj":
        source = next(p for p in profile.projects if p.id == new_id)
        checks.append(((entry.name, entry.repo_url) == (source.name, source.repo_url), "Name and link from the profile"))
        checks.append(([p.id for p in old.projects].index(old_id) == [p.id for p in new.projects].index(new_id),
                       "Takes the old project's place"))
        text = " ".join([source.name, source.description, source.readme] + source.bullets).lower()
        foreign = [t for t in entry.tech_stack if t.lower() not in text]
        checks.append((not foreign, "Every tool in its tech stack is named in its own profile text"
                       + (f"; not found: {foreign}" if foreign else "")))
        moved = [t for p in old.projects if p.id == old_id for t in p.tech_stack
                 if t.lower() in " ".join(entry.bullets).lower() and t.lower() not in text]
        checks.append((not moved, "No tool from the replaced project in its bullets" + (f": {moved}" if moved else "")))
    elif kind == "exp":
        source = next(e for e in profile.experience if e.id == new_id)
        checks.append(((entry.title, entry.organization, entry.duration)
                       == (source.title, source.organization, format_range(source)), "Title, employer and dates from the profile"))
        dates = {e.id: recency_key(e) for e in profile.experience}
        order = [e.id for e in new.experience]
        checks.append((order == sorted(order, key=lambda i: dates.get(i, ("", "")), reverse=True),
                       f"Experience newest first: {order}"))
    else:
        source = next(c for c in profile.courses if c.id == new_id)
        checks.append((entry == nodes.cv_course(source), "Course name, provider and date from the profile"))
        return checks

    profile_bullets = (source.bullets or getattr(source, "responsibilities", []))[:nodes.MAX_CV_BULLETS]
    if entry.bullets == profile_bullets:
        checks.append((None, "Its bullets are the saved profile bullets: the model wrote none"))
    else:
        checks.append((3 <= len(entry.bullets) <= 5, f"{len(entry.bullets)} tailored bullets (3-5 asked)"))

    if old.objective != new.objective:
        checks.append((None, "The objective changed: check it only drops what the replaced item showed"))
    if old.skills != new.skills:
        added = [s for s in new.skills if norm(s) not in {norm(o) for o in old.skills}]
        gone = [s for s in old.skills if norm(s) not in {norm(n) for n in new.skills}]
        checks.append((None, f"Skills changed: added {added or 'none'}, removed {gone or 'none'}"))
        source_text = (json.dumps(st.session_state["run_profile"], ensure_ascii=False) + " "
                       + " ".join(match.relevant_skills)).lower()
        unsupported = [s for s in added if s.lower() not in source_text]
        checks.append((not unsupported, "Added skills appear in the profile or the match's relevant skills"
                       + (f"; not found: {unsupported}" if unsupported else "")))
    missing_text = " ".join(m.requirement for m in match.missing).lower()
    claimed = sorted({t for t in getattr(entry, "tech_stack", []) + new.skills if t.lower() in missing_text
                      and norm(t) not in {norm(s) for s in old.skills}})
    if claimed:
        checks.append((False, f"New terms that are in NEVER CLAIM: {claimed}"))
    return checks


def example_swaps(cv: FinalCV, match: JobMatch) -> list[tuple[str, str, str]]:
    """(old id, new id, what to look for): up to two candidates for each item on the CV, best first."""
    hints = {"exp": "the experience list stays newest first", "proj": "takes the old project's place, own stack only",
             "course": "no LLM call"}
    swaps = []
    for item_id in nodes.cv_item_ids(cv):
        for candidate in nodes.swap_candidates(cv, item_id, match)[:2]:
            hint = f"{RELEVANCE_LABELS[candidate.relevance]}; {hints[item_id.split('_')[0]]}"
            swaps.append((item_id, candidate.id, hint))
    return swaps


def render_swap_scenario(cv: FinalCV) -> None:
    """One-click swaps for this run, and the steps to try around them."""
    swaps = example_swaps(cv, JobMatch.model_validate(st.session_state["job_match"]))
    if not swaps:
        st.caption("Every profile item is already on this CV, so there is nothing to swap.")
        return
    for n, (old_id, new_id, hint) in enumerate(swaps):
        st.button(f"{swap_label(old_id, new_id)}  ({hint})", key=f"example_swap_{n}", disabled=versions.is_editing(DOC),
                  on_click=request_swap, args=(old_id, new_id), width="stretch")
    st.caption("Then try: Undo and Redo (no LLM call, no report); a revision that names the new item (the "
               "revise call should see it); swapping the old item back in (written again, not restored); "
               "Edit, where the swap menus disappear until you save or cancel.")


# --- Report -----------------------------------------------------------------------------

def render_diff(before: dict, after: dict) -> None:
    old, new = FinalCV.model_validate(before), FinalCV.model_validate(after)
    if old == new:
        st.caption("The CV didn't change.")
        return

    def side_by_side(title: str, old_lines: list[str], new_lines: list[str]) -> None:
        st.markdown(f"**{md(title)}**")
        left, right = st.columns(2)
        left.caption("Before")
        left.markdown("\n".join(f"- {md(l)}" if l in new_lines else f"- ~~{md(l)}~~" for l in old_lines) or "—")
        right.caption("After")
        right.markdown("\n".join(f"- {md(l)}" if l in old_lines else f"- **+** {md(l)}" for l in new_lines) or "—")

    if old.objective != new.objective:
        side_by_side("Objective", [old.objective], [new.objective])
    if old.skills != new.skills:
        side_by_side("Skills", [", ".join(old.skills)], [", ".join(new.skills)])
        gone = [s for s in old.skills if s not in new.skills]
        added = [s for s in new.skills if s not in old.skills]
        st.caption(f"Added: {md(', '.join(added)) or 'none'} · Removed: {md(', '.join(gone)) or 'none'}")
    def label(entry) -> str:
        return getattr(entry, "name", None) or f"{entry.title.strip()} ({entry.organization.strip()})"

    # Items are paired by id (by place for old logs without ids), so a swapped-in item shows as new.
    old_items = [(o.id or f"#{n}", o) for n, o in enumerate(old.projects + old.experience)]
    new_items = [(i.id or f"#{n}", i) for n, i in enumerate(new.projects + new.experience)]
    old_by_key = dict(old_items)
    for key, o in old_items:
        if key not in dict(new_items):
            st.markdown(f"**Swapped out:** {md(label(o))} [{md(o.id)}]")
    for key, n in new_items:
        o = old_by_key.get(key)
        if o is None:
            side_by_side(f"Swapped in: {label(n)} [{n.id}]: bullets", [], n.bullets)
            if hasattr(n, "tech_stack"):
                st.caption(f"Tech stack: {md(', '.join(n.tech_stack)) or 'none'}")
            continue
        if o.bullets != n.bullets:
            side_by_side(f"{label(o)} [{o.id}]: bullets", o.bullets, n.bullets)
        if getattr(o, "tech_stack", None) != getattr(n, "tech_stack", None):
            side_by_side(f"{label(o)} [{o.id}]: tech stack", [", ".join(o.tech_stack)], [", ".join(n.tech_stack)])
    if old.courses != new.courses:
        side_by_side("Courses", [c.name for c in old.courses], [c.name for c in new.courses])
    if [e.id for e in old.experience if e.id in {n.id for n in new.experience}] != \
            [e.id for e in new.experience if e.id in {o.id for o in old.experience}]:
        st.caption("The experience order changed.")


def render_report(report: dict) -> None:
    icons = {True: "✅", False: "❌", None: "⚠️"}
    st.markdown("\n".join(f"- {icons[ok]} {md(what)}" for ok, what in report["checks"]))
    st.caption(f"{report['seconds']} s · " + ", ".join(f"{c['task']}: {c['model']}" for c in report["calls"]))
    render_diff(report["before"], report["after"])
    for call in report["calls"]:
        with st.expander(f"What the model saw ({call['task']})"):
            st.code(call["user_text"], language=None)
        with st.expander(f"What the model returned ({call['task']})"):
            st.json(call["result"])


st.set_page_config(page_title="CV revision test", page_icon="✏️", layout="wide")
st.title("CV revision and swap test")

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
    reload = st.button("Start over from the saved CV", help="Drops every revision made to this run here.")
    st.caption(f"Revise model: {model_for('revise')} (effort {TASK_MODELS['revise'][1]})  \n"
               f"Swap model: {model_for('swap')} (effort {TASK_MODELS['swap'][1]})")

if upload is None and run_path is None:
    st.info("No saved runs in TestRunJson/ or the project folder; upload one in the sidebar.")
    st.stop()

try:
    run, saved_cv = load_uploaded(upload) if upload is not None else load_run(run_path)
    profile = StructuredProfile.model_validate(run["structured_profile"])
except SystemExit as exc:  # load_final_cv exits on a run without a final_cv
    st.error(str(exc))
    st.stop()
except Exception as exc:
    st.error("This run couldn't be read:")
    st.code(str(exc))
    st.stop()

run_key = f"upload:{upload.name}:{upload.size}" if upload is not None else str(run_path)
if reload or st.session_state.get("loaded_run") != run_key:
    cv, filled, unmatched = backfill_ids(saved_cv, profile)
    clear_job()  # the app's job state: what its revise_cv and editor read and write
    versions.start(DOC, cv.model_dump(), "Saved run")
    st.session_state.update(
        loaded_run=run_key, reports=[], id_notes=(filled, unmatched),
        run_profile=run["structured_profile"], parsed_jd=run["structured_jd"], job_match=run["job_match"],
    )

jd = run["structured_jd"]
missing = run["job_match"].get("missing", [])
with st.sidebar:
    with st.expander(f"NEVER CLAIM ({len(missing)})"):
        st.markdown("\n".join(f"- *{m['importance']}*: {md(m['requirement'])}" for m in missing)
                    or "Nothing.")

st.caption(f"Run: {upload.name if upload is not None else run_path.name}  ·  Job: "
           f"{md(jd.get('title')) or '?'}" + (f" at {md(jd['company'])}" if jd.get("company") else ""))
filled, unmatched = st.session_state["id_notes"]
if filled:
    st.caption("This log predates CV item ids; matched from the profile: " + md("; ".join(filled)))
if unmatched:
    st.warning("No profile entry found for: " + md("; ".join(unmatched))
               + ". Revisions can't change these items.")

if swap := take_swap():  # picked in a swap menu on the preview or with a scenario button
    old_id, new_id = swap
    try:
        with st.spinner(f"{swap_label(old_id, new_id)} with {model_for('swap')}..."):
            record(swap_label(old_id, new_id), lambda: swap_item(old_id, new_id),
                   check=lambda before, after, calls: swap_checks(before, after, calls, old_id, new_id))
    except Exception as exc:
        st.error("The swap failed:")
        st.code(str(exc))
    else:
        st.rerun()  # draw the preview and the report with the new CV

cv_col, revise_col = st.columns([3, 2], gap="large")

index, total = versions.position(DOC)
editing = versions.is_editing(DOC)  # the LLM, Undo and Redo wait until the edit is saved
with cv_col:
    st.subheader(f"CV · version {index + 1} of {total}")
    st.button("✏️ Edit", on_click=versions.set_editing, args=(DOC, True), disabled=editing)
    if record(MANUAL, editable_cv):
        st.rerun()  # draw the preview again with the edited CV

with revise_col:
    st.subheader("Revise")
    examples = example_requests(saved_cv)
    st.selectbox("Example request", examples, index=None, key="example", placeholder="Pick one to fill the box…",
                 on_change=lambda: st.session_state.update(
                     request=(st.session_state["example"] or "").split("  [")[0]))
    request = st.text_area("What should change?", key="request", placeholder=REVISION_PLACEHOLDER,
                           height=110)
    revise_clicked = st.button("Revise with the LLM", type="primary", disabled=editing)
    undo_col, redo_col = st.columns(2)
    undo_col.button("↩ Undo", on_click=versions.go_to, args=(DOC, index - 1), disabled=index == 0 or editing)
    redo_col.button("↪ Redo", on_click=versions.go_to, args=(DOC, index + 1), disabled=index == total - 1 or editing)

    if revise_clicked:
        if not request.strip():
            st.warning("Write what should change first.")
        else:
            try:
                with st.spinner(f"Revising with {model_for('revise')}..."):
                    record(request.strip(), lambda: revise_cv(request.strip()))
            except Exception as exc:
                st.error("The revision failed:")
                st.code(str(exc))
            else:
                st.rerun()  # the preview is drawn left of the form, so draw it again with the new CV

    with st.expander("Swap scenario: one click per swap", icon="🔀"):
        render_swap_scenario(FinalCV.model_validate(versions.current(DOC)))

    if last := versions.last_change(DOC):
        render_revision_result(last)

    reports = st.session_state["reports"]
    if reports:
        st.subheader("Report")
        st.markdown(f"**Request:** {md(reports[-1]['request'])}")
        render_report(reports[-1])
    for number, report in reversed(list(enumerate(reports[:-1], start=1))):
        with st.expander(f"Revision {number}: {report['request'][:70]}"):
            render_report(report)

    st.divider()
    final_cv = FinalCV.model_validate(versions.current(DOC))
    st.download_button("Download CV (PDF)", data=render_cv_pdf(final_cv),
                       file_name=f"{safe_filename(final_cv.name, 'cv')}_cv.pdf", mime="application/pdf")
    revised_run = {  # same shape as the app's run download, with this session's revisions
        **run, "saved_at": datetime.now().isoformat(timespec="seconds"),
        "models": {task: model_for(task) for task in TASK_MODELS},
        "final_cv": versions.current(DOC), "revisions": versions.log(DOC),
    }
    st.download_button("Download run (JSON)", data=json.dumps(revised_run, indent=2, ensure_ascii=False),
                       file_name=f"{datetime.now():%Y%m%d_%H%M%S}_{safe_filename(jd.get('title'), 'run')}.json",
                       mime="application/json")
