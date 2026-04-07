from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class CandidateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr


class CandidateCreate(CandidateBase):
    job_id: int


class CandidateResponse(CandidateBase):
    id: int
    job_id: int
    resume_filename: str
    fit_score: Optional[float] = None
    hire_probability: Optional[float] = None
    cluster_label: Optional[str] = None
    status: str
    shortlist_status: str = "none"
    created_at: datetime

    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: str = Field(..., min_length=10)
    required_skills: str = Field(..., min_length=2)
    min_experience: int = Field(0, ge=0)


class JobResponse(JobCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class JobDetail(JobResponse):
    candidates: list[CandidateResponse] = Field(default_factory=list)


class ShortlistDecisionUpdate(BaseModel):
    decision: Literal["none", "shortlisted", "rejected"]
