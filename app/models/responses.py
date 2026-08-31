from datetime import datetime

from pydantic import BaseModel


class Experience(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    duration: str | None = None
    description: str | None = None


class Education(BaseModel):
    school: str | None = None
    degree: str | None = None
    duration: str | None = None


class Certification(BaseModel):
    name: str | None = None
    issuer: str | None = None
    date: str | None = None


class ProfileResponse(BaseModel):
    profile_url: str
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    about: str | None = None
    profile_image_url: str | None = None
    experience: list[Experience] = []
    education: list[Education] = []
    skills: list[str] = []
    certifications: list[Certification] = []
    languages: list[str] = []
    scraped_at: datetime
    # Non-fatal per-field extraction issues (e.g. "skills list may be
    # truncated"). Empty list means clean extraction, not "field omitted".
    warnings: list[str] = []


class StatusResponse(BaseModel):
    status: str
    connected_at: str | None = None


class ErrorResponse(BaseModel):
    error: str
    detail: str
