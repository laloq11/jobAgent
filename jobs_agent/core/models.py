from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, HttpUrl

Source = Literal[
    "bundesagentur", "arbeitnow", "indeed", "adzuna", "jsearch", "career_page", "manual",
    "rss", "watch", "cea", "nadigest", "jobsacuk", "websearch",
]

Status = Literal[
    "not_started", "needs_review", "rejected", "approved_draft", "drafting",
    "needs_final_review", "ready_to_submit", "submitted",
    "follow_up", "interview_scheduled", "closed", "ignore", "low_fit",
]

FirstAnswer = Literal["Yes", "No"]


class JobPosting(BaseModel):
    role: str
    company: str
    url: HttpUrl
    source: Source
    location: str = ""
    deadline: Optional[date] = None
    fit_score: Optional[float] = None
    summary: str = ""
    status: Status = "not_started"
    cover_letter_path: str = ""
    cv_path: str = ""
    todo: str = ""
    application_date: Optional[date] = None
    first_interview: Optional[date] = None
    first_answer: Optional[FirstAnswer] = None
    notes: str = ""
    description: str = ""  # full text, cached locally only (not sent to Notion)
