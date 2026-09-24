from typing import Optional
from pydantic import BaseModel, Field
class ContactInfo(BaseModel):
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class EducationEntry(BaseModel):
    course_name: str
    institution: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[str] = None
class ProfileProject(BaseModel):
    name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    repo_url: Optional[str] = None
    outcomes: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)

class ProfileExperience(BaseModel):
    title: str
    organization: str
    duration: Optional[str] = None
    responsibilities: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)

class Certification(BaseModel):
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

class BulletList(BaseModel):
    bullets: list[str] = Field(default_factory=list)

class StructuredJD(BaseModel):
    title: str
    company: Optional[str] = None
    seniority: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

class GapAnalysis(BaseModel):
    matched_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    missing_preferred_skills: list[str] = Field(default_factory=list)
    relevant_projects: list[str] = Field(default_factory=list)      # by name
    relevant_experience: list[str] = Field(default_factory=list)    # by title/org
    low_relevance_projects: list[str] = Field(default_factory=list) # candidates to de-emphasize
    notes: Optional[str] = None

class GeneratedCVProject(BaseModel):
    name: str
    bullets: list[str] = Field(default_factory=list)

class GeneratedCVExperience(BaseModel):
    title: str
    organization: str
    bullets: list[str] = Field(default_factory=list)

class GeneratedCVContent(BaseModel):
    objective: str
    skills: list[str] = Field(default_factory=list)
    projects: list[GeneratedCVProject] = Field(default_factory=list)
    experience: list[GeneratedCVExperience] = Field(default_factory=list)

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