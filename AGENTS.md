# AGENTS.md

Guidance for coding agents (and people) working on this repo. [README.md](README.md) is the
user-facing description; this file is about how to change the code safely.

## What this is

JobFit is a single-user, local Streamlit app. The user saves a profile once, pastes a job
description, and the app parses the job, ranks every profile item against it, and writes a
tailored CV (PDF), a short cover letter, or suggestions for closing the gaps. Built with
LangGraph, OpenAI models via `langchain-openai`, Pydantic structured output, Streamlit and
ReportLab.

## Setup and run

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows; macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # put OPENAI_API_KEY in .env; GITHUB_TOKEN is optional
streamlit run app.py
```

Python 3.10+. Run everything from the repo root (`app.py` imports the `jobfit` package).

## Where things live

| File | What it holds |
|---|---|
| `app.py` | Entry point: page setup, sidebar, the Profile / Job application / History pages |
| `jobfit/graph.py` | The two LangGraph pipelines: profile (intake → READMEs → bullets) and application (parse JD → match → CV / letter / suggestions) |
| `jobfit/state.py` | `AgentState`, the shared state passed through both graphs |
| `jobfit/nodes.py` | Every graph node, the routing functions, and the code that validates LLM output |
| `jobfit/models.py` | Pydantic schemas: profile, JD, match, gap plan, CV, cover letter, revisions |
| `jobfit/prompts.py` | All LLM system prompts |
| `jobfit/llm.py` | `TASK_MODELS` (model and reasoning effort per task) and `extract_structured` |
| `jobfit/formatting.py` | Turns the profile, JD and match into plain text for prompts |
| `jobfit/github_repo.py` | GitHub URL parsing and README fetching / cleaning |
| `jobfit/storage.py`, `jobfit/history.py` | `data/profile.json` with id assignment; saved jobs in `data/history/` |
| `jobfit/render_cv.py`, `jobfit/render_letter.py` | PDF (and plain-text) rendering |
| `jobfit/ui/` | Streamlit UI, one module per page or section |

## Rules that must hold

These are the reason the app's output can be trusted. Don't break them when adding features.

1. **The LLM refers to profile items by id, code fills in the facts.** Items have stable ids
   (`proj_1`, `exp_1`, `course_1`, `cert_1`) and id numbers are never reused. Names, dates,
   tech stacks, links, contact details, greetings and sign-offs are copied from the saved
   profile and the parsed JD in code, never taken from the LLM. After every LLM call, code
   drops unknown or duplicate ids and caps list lengths (see the `MAX_*` constants in `nodes.py`).
2. **Never claim what the profile doesn't show.** Missing requirements from the match are passed
   to the CV, letter and revision prompts as things never to claim. A revision request that asks
   for a missing skill goes in `not_done`; it isn't applied.
3. **The match is the only relevance decision.** `pick_for_cv` and `pick_for_letter` in `nodes.py`
   choose the items from the ranking. The writers see only the items picked and never choose
   items themselves.
4. **Say about the company only what the job posting says.**
5. **Personal data stays local.** `data/` and `.env` are git-ignored; never commit them, and don't
   add test fixtures built from a real profile.

## How the code is written

- **Structured output only.** Every LLM call goes through `extract_structured(task, prompt, text,
  Schema)` with a Pydantic schema. Field descriptions in `models.py` are part of the prompt, so
  keep them short and exact.
- **Models are picked per task** in `TASK_MODELS` in `llm.py`, and each can be overridden with a
  `MODEL_<TASK>` env var. A new LLM step adds a task there; don't hard-code a model in a node.
- **Nodes skip themselves when their result is already in the state** (for example, a CV passed in
  for a revision). The UI relies on this to avoid repeating the parse and the match, so a
  revision costs one LLM call.
- **Saved data must stay readable.** History entries are plain JSON validated against the models.
  A new field needs a default, so older saved jobs still open.
- **Style:** short functions with a one-line docstring, comments only where the reason isn't
  obvious, type hints, no new dependencies without a clear need. Match the surrounding code.

## Adding a step

1. Schema in `models.py` (what the LLM returns, and the final object if it differs).
2. Prompt in `prompts.py`: inputs in `=== SECTION ===` blocks, outputs and truth rules spelled out.
3. Task and model in `TASK_MODELS`.
4. Node in `nodes.py` that builds the input text with `formatting.py`, calls the LLM, then
   validates and fills in facts in code. New state keys go in `state.py`.
5. Wire it into `graph.py` (a new `mode` branch or an edge).
6. UI in `jobfit/ui/`, and add the result to `run_snapshot` in `ui/job_run.py` if it should be saved
   in History.
7. Update `README.md` (Features, Configuration, Architecture) to match.

## Checking a change

There are no automated tests yet. After a change:

- Run `streamlit run app.py`, save the profile, analyse a real job posting and go through the
  tabs the change touches, including Undo / Redo and PDF download where relevant.
- Save the job to History and open it again: it must come back exactly as saved, with no LLM call.
- For prompt changes, try a short job post, a long noisy one, and a profile with few items. Compare
  the saved History JSON before and after, and check that nothing invented or missing was claimed.
- Watch for calls that shouldn't happen: saving an unchanged profile or editing contact details
  should make no LLM call.
