# Project Status — Group Ares

**Members:** Diwas Kharel, Bikash Bashyal, Biswash Pokhrel
**Repository:** https://github.com/hamk-ai-autumn-2026/jobsearch-agent

## Change of direction

Our first plan was a pipeline that finds and ranks job postings for a CV and then mass-sends
application emails. After the teacher's review we changed the problem we are solving:
finding jobs is the easy part. Getting one is hard, because a posting often has 100–300
applicants. The project now focuses on **helping one candidate stand out for one specific
job**, rather than on applying to many jobs.

## 1. What the prototype does

A local Streamlit app. The user fills out their profile once (education, projects,
experience, skills, certifications). Then they paste a job description and the agent:

- parses the job into requirements, preferred skills, tech stack and ATS keywords
- ranks every profile item by how relevant it is to the job and lists the missing requirements
- then either:
  - **Tailor CV:** writes a job-specific CV (objective, skills, reworded bullets) and exports
    it as a PDF. It never claims a skill the user doesn't have.
  - **Recommend for gaps:** writes a prioritised plan to close the gaps: add-ons to existing
    projects, small new projects, courses or certifications, and honest advice for gaps that
    can't be closed quickly.

The LLM refers to profile items only by id, and code fills in names and facts from the
saved profile, which keeps the output from inventing things.

## 2. Technologies

| Area | Technology |
|---|---|
| Orchestration | LangGraph (two graphs over a shared state, with a CV / gap-plan branch) |
| LLM | OpenAI models (`gpt-5`, `gpt-5-mini`) via `langchain-openai` |
| Structured output | Pydantic schemas for the profile, job, match, CV and gap plan |
| Frontend | Streamlit |
| PDF export | ReportLab |
| Storage | Local JSON file (`data/profile.json`) |
| Language | Python 3.10+ |

## 3. TODO (in priority order)

1. **Import projects from a GitHub link.** The user pastes a repo URL in the project section
   and the agent reads the repo (README, languages, structure) to build the project
   description. Right now the user has to copy-paste the README by hand.
2. **Interactive follow-up questions (human-in-the-loop).** The gap plan already returns
   `maybe_already_have`, hints about experience the user may have left out. Let the user
   answer these mid-run, save the answers to the profile, and base the next CV or
   recommendation on them. This is where LangGraph's interrupt/resume is actually useful.
3. **Cover letter.** Generate a tailored cover letter next to the CV and the recommendations,
   using the same match result.
4. **Clean-up and a better frontend.** Refactor the prototype code and improve the UI so it
   can grow (clearer flow, editable outputs, better result views).
5. *(Optional)* **Automated email.** Draft and send the application by email when the job
   asks for it. Sending stays behind manual approval, with dry-run as the default.
6. *(Optional)* **Job scraping.** Fetch postings the user searched for and use their
   descriptions directly, instead of pasting them. The scope is not decided yet: only jobs
   the user searched for, or also matched ones.

## 4. Updated weekly schedule

| Week | Status | Focus | Work |
|---|---|---|---|
| 1 | ✅ Done | Pivot & foundation | Re-scoped the project after the teacher's review; profile schema, form and local storage; job description parser with structured output |
| 2 | ✅ Done | Core prototype | Profile-vs-job matching; tailored CV with PDF export; gap recommendations; LangGraph pipeline with the CV / gaps branch; run snapshots |
| 3 | ⏳ Next | GitHub import & interactive agent | Build project descriptions from a pasted GitHub repo link (README, languages, structure); human-in-the-loop with a LangGraph interrupt, where the user answers the `maybe_already_have` questions, the answers update the profile, and the CV and recommendations are re-run from them |
| 4 | Planned | Cover letter & frontend | Generate a cover letter from the match result; code clean-up and a better UI (CV, cover letter and gap plan in one view); *(optional)* email sending with dry-run and manual approval; *(optional)* scraping jobs the user searched for |
| 5 | Planned | Testing & demo | Output quality checks with run snapshots; prompt tuning; edge cases (private repos, empty READMEs, short job posts); bug fixes; demo, report and presentation |
