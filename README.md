# Job Search Agent

A Streamlit app that reviews a candidate's profile against a pasted job description:
it ranks every experience, project, course and certificate by relevance, lists the
relevant skills, lists the job requirements the profile doesn't cover yet, and
generates a tailored PDF CV.

## What it does

1. **Profile intake** — the user fills out a form (education, projects, experience,
   skills, certifications, contact info, links). Raw project/experience descriptions
   are rewritten into resume-style bullet points by an LLM and the profile is saved
   to disk as JSON.
2. **Profile vs job** — the user pastes a job description. The app parses it, then
   in one LLM call:
   - ranks each profile item (high / medium / low / none) with a one-line reason,
   - lists the candidate's skills relevant to this job,
   - lists the missing requirements — what no item or skill covers, with a note on
     what exactly is lacking. This list is the input for suggesting new projects later.
3. **CV** — tailored CV content (objective, skills, best projects and experience with
   reworded bullets) is generated from the match and rendered to a PDF.

The whole thing is a single-user local app — one profile, stored as one JSON file.

## Architecture

Two [LangGraph](https://github.com/langchain-ai/langgraph) pipelines (`graph.py`),
each a linear chain of nodes over a shared `AgentState` (`state.py`).

```
Profile tab:  intake_profile → format_bullets
JD tab:       parse_jd → match_profile → generate_cv_content
```

- **`intake_profile_node`** — validates the form into a `StructuredProfile` and gives
  every entry a persisted id (`proj_1`, `exp_1`, `cert_1`, `edu_1`) via
  `storage.assign_profile_ids`, so the LLM can refer to items unambiguously.
- **`format_bullets_node`** — turns each project/experience description into 3–15
  resume-ready bullets.
- **`parse_jd_node`** — extracts a `StructuredJD` (title, company, requirements,
  preferred, responsibilities, tech stack, keywords).
- **`match_profile_node`** — one LLM call returns a `JobMatch` (ranked items,
  relevant skills, missing requirements). Code only drops unknown ids, attaches item
  names, and adds any item the model skipped as `none`.
- **`generate_cv_content_node`** — the LLM picks projects/experience by id and writes
  tailored bullets; names, tech stacks, urls and durations are copied from the saved
  profile into a `FinalCV`.

## File map

| File | Responsibility |
|---|---|
| `streamlit_app.py` | UI — profile form + job description tab |
| `graph.py` | LangGraph pipeline definitions |
| `state.py` | Shared `AgentState` passed through each graph |
| `nodes.py` | Graph node implementations |
| `model.py` | Pydantic schemas (profile, JD, match, CV) |
| `prompts.py` | LLM system prompts |
| `llm.py` | Structured-output LLM calls; picks a model per task (`gpt-5-mini` for bullets and JD parsing, `gpt-5` for matching, CV and gap plans), overridable with `MODEL_<TASK>` env vars |
| `formatting.py` | Profile / JD / match → plain text for LLM prompts |
| `storage.py` | Load/save the local profile JSON, assign entry ids |
| `render_cv.py` | Final CV → PDF (ReportLab) |

## Next

A `suggest_projects` node that takes `JobMatch.missing` and proposes project ideas
that would close those gaps.
