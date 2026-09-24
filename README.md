# Job Search Agent

A Streamlit app that takes a candidate's profile, tailors it against a pasted job
description using an LLM, and outputs a ready-to-download PDF CV.

## What it does

1. **Profile intake** — the user fills out a form (education, projects, experience,
   skills, certifications, contact info, links). Raw project/experience descriptions
   are rewritten into resume-style bullet points by an LLM and the structured profile
   is saved to disk as JSON.
2. **Job tailoring** — the user pastes a job description. The app parses it into
   structured fields, compares it against the saved profile (gap analysis), and
   generates tailored CV content (objective, skill subset, selected/reworded project
   and experience bullets) that draws only on what's actually in the profile.
3. **PDF export** — the tailored content is rendered into a formatted CV PDF.

The whole thing is a single-user local app — one profile, stored as one JSON file.

## Architecture

The app is built as two [LangGraph](https://github.com/langchain-ai/langgraph)
pipelines, each a linear chain of nodes operating on a shared `AgentState`
(`state.py`), a `TypedDict` that accumulates fields as it moves through the graph.

### `build_profile_graph()` (`graph.py`)

Runs when the profile form is submitted.

```
intake_profile → format_bullets
```

- **`intake_profile_node`** — validates the raw form dict from Streamlit into a
  `StructuredProfile` (pydantic model, `model.py`).
- **`format_bullets_node`** — for each project and experience entry, sends the raw
  description/responsibilities through the LLM with `PROJECT_BULLETS_SYSTEM_PROMPT`
  or `EXPERIENCE_BULLETS_SYSTEM_PROMPT` (`prompts.py`) to produce 3–15 resume-ready
  bullets per entry. Entries with too little source text (`MIN_SOURCE_LEN`) are
  skipped rather than hallucinated.

The result is a fully structured, bulleted profile, saved via `storage.save_profile`.

### `build_application_graph()` (`graph.py`)

Runs when a job description is submitted, taking the saved profile as input.

```
parse_jd → gap_analysis → generate_cv_content
```

- **`parse_jd_node`** — extracts a `StructuredJD` (title, company, seniority,
  required/preferred skills, responsibilities, tech stack, keywords) from the raw
  pasted text.
- **`gap_analysis_node`** — compares the structured profile against the structured
  JD and produces a `GapAnalysis`: matched skills, missing required/preferred
  skills, which projects/experience are relevant vs. low-relevance.
- **`generate_cv_content_node`** — given the JD, profile, and gap analysis, asks the
  LLM to produce `GeneratedCVContent` (objective, skill subset, selected projects
  and experience with tailored bullets). The gap analysis is treated as a hint, not
  a mandate. The node then cross-checks every generated project/experience/skill
  name against the original profile entries (`projects_by_name`,
  `experience_by_key`, `known_skills`) and drops anything that doesn't match a real
  entry, assembling the final `FinalCV`.

### LLM extraction (`llm.py`)

A single helper, `extract_structured(system_prompt, user_text, schema)`, wraps
`ChatOpenAI(model="gpt-5-mini")` with LangChain's `with_structured_output`, used by
every node above to get typed pydantic output from the LLM in one call.

### Prompts (`prompts.py`)

All system prompts live here, one per LLM call: `JD_SYSTEM_PROMPT`,
`PROJECT_BULLETS_SYSTEM_PROMPT`, `EXPERIENCE_BULLETS_SYSTEM_PROMPT`,
`GAP_ANALYSIS_SYSTEM_PROMPT`, `CV_CONTENT_SYSTEM_PROMPT`. They share a consistent
rule: only use information present in the source, never invent skills, tools,
metrics, or outcomes.

### Data models (`model.py`)

Pydantic models form the contract between every node and the UI:

- `StructuredProfile` (+ `ProfileProject`, `ProfileExperience`, `EducationEntry`,
  `Certification`, `ContactInfo`) — the canonical saved profile.
- `StructuredJD` — parsed job description.
- `GapAnalysis` — profile-vs-JD comparison.
- `GeneratedCVContent` (+ `GeneratedCVProject`, `GeneratedCVExperience`) — raw LLM
  output for tailored content, referencing profile entries by name only.
- `FinalCV` (+ `FinalCVProject`, `FinalCVExperience`) — the validated, ready-to-render
  CV, built by merging `GeneratedCVContent` back with the original profile data
  (so tech stacks, repo URLs, durations, etc. always come from the source of truth,
  never the LLM).

### Formatting (`formatting.py`)

Turns `StructuredJD`, `StructuredProfile`, and `GapAnalysis` objects into plain-text
blocks (`format_jd`, `format_profile_for_gap_analysis`, `format_gap_analysis`) that
get concatenated into the `user_text` passed to the LLM in `nodes.py`.

### Storage (`storage.py`)

Single-user, single-file persistence: `load_profile()` / `save_profile()` read and
write `data/profile.json` as a serialized `StructuredProfile`. The module docstring
notes that multi-user support later just means keying this path by user id — no
structural change needed.

### PDF rendering (`render_cv.py`)

`render_cv_pdf(cv: FinalCV) -> bytes` builds a formatted PDF with ReportLab
(`SimpleDocTemplate` + `Paragraph`/`ListFlowable` flowables): name, contact line,
objective, skills, experience, projects, education — each section only rendered if
present.

### UI (`streamlit_app.py`)

Two tabs:

- **Profile** — a form that mirrors `StructuredProfile`'s shape (dynamic entry
  counts for education/projects/experience/certifications), pre-filled from the
  existing saved profile if any. On submit, runs the profile graph and saves the
  result.
- **Job Description** — a text area for pasting a JD. On submit, runs the
  application graph against the saved profile and stores the parsed JD, gap
  analysis, and final CV in `st.session_state`, with `st.json` previews and
  download buttons for the parsed JD (JSON) and the generated CV (PDF, rendered
  on demand via `render_cv_pdf`).

## File map

| File | Responsibility |
|---|---|
| `streamlit_app.py` | UI — profile form + JD tailoring tab |
| `graph.py` | LangGraph pipeline definitions |
| `state.py` | Shared `AgentState` passed through each graph |
| `nodes.py` | Graph node implementations |
| `model.py` | Pydantic schemas (profile, JD, gap analysis, CV) |
| `prompts.py` | LLM system prompts |
| `llm.py` | Structured-output LLM call wrapper |
| `formatting.py` | Structured models → plain text for LLM prompts |
| `storage.py` | Load/save the local profile JSON |
| `render_cv.py` | Final CV → PDF (ReportLab) |
