from typing import Literal, Optional
from pydantic import BaseModel, Field
class ContactInfo(BaseModel):
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

# Profile entries carry a code-assigned id (proj_1, exp_1, cert_1, edu_1) that is
# persisted in profile.json and survives edits — see storage.assign_profile_ids.
class EducationEntry(BaseModel):
    id: Optional[str] = None
    course_name: str
    institution: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[str] = None
class ProfileProject(BaseModel):
    id: Optional[str] = None
    name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    repo_url: Optional[str] = None
    outcomes: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)

class ProfileExperience(BaseModel):
    id: Optional[str] = None
    title: str
    organization: str
    duration: Optional[str] = None
    responsibilities: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)

class Certification(BaseModel):
    id: Optional[str] = None
    name: str
    issuer: Optional[str] = None
    date: Optional[str] = None

class StructuredProfile(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    contact: Optional[ContactInfo] = None
    skills: list[str] = Field(default_factory=list)
    projects: list[ProfileProject] = Field(default_factory=list)
    experience: list[ProfileExperience] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    links: dict[str, str] = Field(default_factory=dict)
    id_counters: dict[str, int] = Field(default_factory=dict)  # highest id number ever issued per prefix

class BulletList(BaseModel):
    bullets: list[str] = Field(default_factory=list)

# --- Job description ---------------------------------------------------------

# Descriptions are sent to the model as part of the structured-output schema.
# (The must-have list is called `requirements`, not `required`, which clashes with the JSON Schema keyword.)
class StructuredJD(BaseModel):
    title: str = Field(description="Job title as stated in the posting")
    company: Optional[str] = Field(default=None, description="Hiring company; null if not stated")
    seniority: Optional[str] = Field(
        default=None, description="Level stated in the title or text (e.g. junior, senior, lead); null if not stated")
    requirements: list[str] = Field(
        default_factory=list,
        description="Every must-have skill, experience, qualification or condition the candidate needs, "
                    "one short phrase each. Almost never empty.")
    preferred: list[str] = Field(
        default_factory=list, description="Nice-to-have items the posting marks as preferred, ideal, a plus or bonus")
    responsibilities: list[str] = Field(default_factory=list, description="Duties of the role, one per entry")
    tech_stack: list[str] = Field(
        default_factory=list,
        description="Named products only (languages, frameworks, databases, cloud services, tools), short names, "
                    "no duplicates; techniques and concepts go in keywords")
    keywords: list[str] = Field(
        default_factory=list, description="Short ATS search terms of 1-4 words; never full sentences")

# --- Profile vs JD match ---------------------------------------------------------

Relevance = Literal["high", "medium", "low", "none"]

class RankedItem(BaseModel):
    id: str                 # proj_1, exp_2, cert_1, edu_1
    relevance: Relevance
    reason: str             # one line: which parts of the JD it matches
    name: str = ""          # filled in by code for display

class MissingRequirement(BaseModel):
    requirement: str
    importance: Literal["required", "preferred", "duty"]  # duty: only from responsibilities/tech stack
    note: str               # e.g. "not mentioned anywhere", "has MySQL, not PostgreSQL"

class JobMatch(BaseModel):
    items: list[RankedItem] = Field(default_factory=list)  # most relevant first
    relevant_skills: list[str] = Field(default_factory=list)
    missing: list[MissingRequirement] = Field(default_factory=list)

# --- Gap recommendations ----------------------------------------------------------
# Gaps are shown to the model as gap_1, gap_2, ... (the order of JobMatch.missing).
# The model fills covers/requirement with those ids; code replaces them with the
# requirement text and drops anything that points at no real gap.

Effort = Literal["hours", "days", "weeks", "months"]

class ProjectAddOn(BaseModel):
    project_id: str             # existing proj_x to extend
    title: str                  # e.g. "Add a PostgreSQL persistence layer"
    steps: list[str] = Field(default_factory=list)   # 2-5 concrete build steps
    covers: list[str] = Field(default_factory=list)  # gap ids
    why_it_fits: str            # how it builds on the project's current stack/design
    effort: Effort
    cv_bullet_preview: str      # bullet the candidate can add once it's actually done
    project_name: str = ""      # filled in by code for display

class NewProjectIdea(BaseModel):
    title: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    covers: list[str] = Field(default_factory=list)
    effort: Effort

class LearningStep(BaseModel):
    topic: str
    kind: Literal["course", "certification", "docs"]
    suggestion: str             # named course/cert/docs, no URLs
    covers: list[str] = Field(default_factory=list)
    effort: Effort

class NotFixableNow(BaseModel):
    requirement: str            # gap id, e.g. years of experience, a degree, a work permit
    how_to_address: str         # e.g. how to frame it in a cover letter or interview

class GapPlan(BaseModel):
    maybe_already_have: list[str] = Field(default_factory=list)  # hints to add unlisted experience to the profile
    project_add_ons: list[ProjectAddOn] = Field(default_factory=list)
    new_projects: list[NewProjectIdea] = Field(default_factory=list)
    learning: list[LearningStep] = Field(default_factory=list)
    not_fixable_now: list[NotFixableNow] = Field(default_factory=list)
    uncovered: list[str] = Field(default_factory=list)  # filled in by code: gaps with no suggestion

# --- CV generation --------------------------------------------------------------

class GeneratedCVItem(BaseModel):
    id: str                 # proj_1 or exp_1
    bullets: list[str] = Field(default_factory=list)

class GeneratedCVContent(BaseModel):
    objective: str
    skills: list[str] = Field(default_factory=list)
    projects: list[GeneratedCVItem] = Field(default_factory=list)
    experience: list[GeneratedCVItem] = Field(default_factory=list)

class FinalCVProject(BaseModel):
    name: str
    tech_stack: list[str] = Field(default_factory=list)
    repo_url: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)

class FinalCVExperience(BaseModel):
    title: str
    organization: str
    duration: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)

class FinalCV(BaseModel):
    name: Optional[str] = None
    contact: Optional[ContactInfo] = None
    objective: str
    skills: list[str] = Field(default_factory=list)
    projects: list[FinalCVProject] = Field(default_factory=list)
    experience: list[FinalCVExperience] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
