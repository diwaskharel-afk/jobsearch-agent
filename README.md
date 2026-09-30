# JobFit

A local Streamlit app that compares a candidate's profile with a pasted job description.
It ranks every project, experience, course and certification by relevance to the job,
lists the relevant skills and the requirements the profile doesn't cover yet, and then
either generates a tailored PDF CV or a concrete plan for closing those gaps.

Built with [LangGraph](https://github.com/langchain-ai/langgraph), OpenAI models via
`langchain-openai`, Pydantic structured output, Streamlit and ReportLab.

## Features

1. **Profile intake.** Fill out a form once: education, courses, projects, experience,
   skills, languages, certifications, contact info and links. Project and experience
   descriptions are rewritten by an LLM into 3–15 resume-style bullets. A project can
   have a description, a GitHub repo URL, or both: the repo's README is read on every
   save and used together with the description to write the bullets. The profile is
   saved to `data/profile.json` and every entry gets a stable id (`proj_1`, `exp_1`,
   `cert_1`, `course_1`). Education has no id: it always goes on the CV as entered.
2. **Profile vs job.** Paste a job description. The app extracts its title, company,
   seniority, requirements, preferred items, responsibilities, tech stack and ATS
   keywords, and then, in one LLM call:
   - ranks each profile item as high / medium / low / none, with a one-line reason
   - lists the candidate's skills relevant to this job
   - lists the missing requirements (required / preferred / duty), with a note on what
     exactly is lacking, e.g. "has MySQL, not PostgreSQL"
3. **Then pick one of two actions:**
   - **Tailor CV.** Writes an objective, a skills list, and the most relevant projects
     and experience with reworded bullets, plus the relevant courses; education is always
     included. It never claims a missing skill. You can
     download the result as a PDF.
   - **Recommend for gaps.** Returns a prioritised plan: add-ons that extend your
     existing projects (with build steps and a preview CV bullet), small new projects,
     courses, certifications or docs, hints for experience you may have left off your
     profile, and honest advice for gaps that can't be closed quickly (degree, years
     of experience, work permit, language).
4. **Run snapshot.** Download a JSON file of each run (parsed JD, match, CV or gap plan,
   the profile used, and the models used) to compare output quality across prompt
   or model changes.

The parsed JD and the match are cached per job description and profile, so switching
between "Tailor CV" and "Recommend for gaps" on the same job doesn't repeat those
LLM calls.

## Getting started

Requirements: Python 3.10+ and an OpenAI API key.

```bash
git clone https://github.com/hamk-ai-autumn-2026/jobsearch-agent.git
cd jobsearch-agent

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env   # then put your OPENAI_API_KEY in .env
streamlit run streamlit_app.py
```

Open the **Profile** tab, fill it out and click **Save profile**. Then go to the
**Job Description** tab, paste a job posting and choose **Tailor CV** or
**Recommend for gaps**.

## Configuration

Settings are read from `.env`:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required. |
| `GITHUB_TOKEN` | Optional. Reads READMEs of private repos and raises GitHub's limit from 60 to 5,000 requests per hour. Public repos work without it. |
| `MODEL_BULLETS` | Model for rewriting descriptions into bullets (default `gpt-6-luna`) |
| `MODEL_PARSE_JD` | Model for parsing the job description (default `gpt-6-luna`) |
| `MODEL_MATCH` | Model for matching the profile to the job (default `gpt-6-sol`) |
| `MODEL_CV` | Model for writing the tailored CV (default `gpt-6-sol`) |
| `MODEL_GAPS` | Model for the gap plan (default `gpt-6-sol`) |

Each task also has a fixed reasoning effort. Both the default models and the efforts are
set in `TASK_MODELS` in `llm.py`.

The simple tasks (bullets, JD parsing) use the low-cost `gpt-6-luna`. The tasks that need
judgment and must stay truthful (match, CV, gap plan) use `gpt-6-sol`. The frontier
`gpt-6-astra` costs 5× as much as Sol, and none of these tasks needs it.

## Architecture

Two LangGraph pipelines (`graph.py`) run over a shared `AgentState` (`state.py`):

```
Profile tab:  intake_profile → fetch_readmes → format_bullets

JD tab:       parse_jd → match_profile ─┬─ mode = "cv"        → generate_cv_content
                                        └─ mode = "recommend" → recommend_gaps
```

- **`intake_profile_node`** validates the form into a `StructuredProfile` and assigns
  persisted ids via `storage.assign_profile_ids`. Id numbers are never reused, so the
  LLM can refer to items unambiguously.
- **`fetch_readmes_node`** reads the README of every project with a GitHub repo URL
  through the GitHub REST API (one request per repo) and strips badges, images and HTML.
  The cleaned README is saved in the project's `readme` field and re-fetched on every
  save, so it always matches the current URL. A repo that can't be read (private,
  missing, rate limit, not on GitHub) gives a warning in the UI but doesn't block saving.
- **`format_bullets_node`** turns each project and experience description into resume
  bullets. For a project with a README, the description and the README are used together,
  with extra prompt rules that skip setup steps, roadmap items and marketing claims.
  Entries with very little text are skipped.
- **`parse_jd_node`** extracts a `StructuredJD`. If the requirements list comes back
  empty, it retries once with a stronger prompt.
- **`match_profile_node`** returns a `JobMatch`. Code drops unknown or duplicate ids,
  attaches display names, and adds any item the model skipped as `none`.
- **`generate_cv_content_node`** lets the LLM choose projects and experience by id and
  write tailored bullets. Names, tech stacks, repo URLs and durations are always copied
  from the saved profile, never from the LLM. The output is a `FinalCV`, which
  `render_cv.py` turns into a PDF.
- **`recommend_gaps_node`** shows the gaps to the LLM as `gap_1`, `gap_2`, ….
  Code then swaps those ids for the requirement text, drops suggestions that cover no
  real gap, sorts suggestions by importance and effort, and lists any gap left
  without a suggestion as `uncovered`.

In short, the LLM refers to things by id and code resolves the ids against the saved
profile. That keeps names and facts from being invented.

## Project structure

| File | Responsibility |
|---|---|
| `streamlit_app.py` | UI: profile form, job description tab, results, downloads |
| `graph.py` | LangGraph pipeline definitions and the CV / gaps branch |
| `state.py` | Shared `AgentState` passed through each graph |
| `nodes.py` | Graph node implementations |
| `model.py` | Pydantic schemas: profile, JD, match, gap plan, CV |
| `prompts.py` | LLM system prompts |
| `llm.py` | Structured-output LLM calls and the model chosen for each task |
| `formatting.py` | Turns the profile, JD and match into plain text for prompts |
| `github_repo.py` | Parses GitHub repo URLs and fetches and cleans a repo's README |
| `storage.py` | Loads and saves `data/profile.json` and assigns entry ids |
| `render_cv.py` | Renders the final CV to PDF with ReportLab |

## Data and privacy

This is a single-user local app: one profile, stored in `data/profile.json`. The `data/`
folder is in `.gitignore`, so personal details are never committed. Profile text, job
descriptions and the READMEs of linked repos (including private ones, if a `GITHUB_TOKEN`
is set) are sent to the OpenAI API for processing.

## Roadmap

- Multiple users (key the profile path by user id)
- Export the tailored CV as editable text or DOCX as well as PDF
- Suggest improvements to existing bullets based on what a job asks for
