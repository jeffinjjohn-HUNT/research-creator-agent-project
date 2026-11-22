"""Structured schemas passed between graph nodes (Pydantic v2)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Platform(str, Enum):
    instagram = "instagram"
    youtube = "youtube"
    x = "x"
    tiktok = "tiktok"
    linkedin = "linkedin"
    reddit = "reddit"
    web = "web"
    news = "news"
    pasted = "pasted"


class ExtractionStatus(str, Enum):
    ok = "ok"
    partial = "partial"  # metadata only (e.g. title/creator, no transcript)
    inaccessible = "inaccessible"  # nothing readable: ask the user for pasted text


class OriginalSource(BaseModel):
    url: str | None = None
    platform: Platform = Platform.web
    title: str | None = None
    creator: str | None = None
    posted_at: str | None = None
    extracted_text: str = ""
    transcript: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.inaccessible
    confidence: Literal["high", "medium", "low", "user_provided"] = "low"
    note: str | None = None  # human-readable explanation of limits


class ClaimDraft(BaseModel):
    text: str
    claim_type: Literal["fact", "opinion", "marketing", "speculation"] = "fact"


class ResearchPlan(BaseModel):
    topic: str
    entities: list[str] = Field(default_factory=list)
    claims: list[ClaimDraft] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


class ResearchQuery(BaseModel):
    platform: str
    query_text: str
    search_time: datetime = Field(default_factory=utcnow)
    result_count: int = 0
    provider: str = ""
    error: str | None = None


class EvidenceSource(BaseModel):
    id: str = ""  # assigned after normalisation: E1, E2, ...
    url: str
    title: str
    platform: str
    author: str | None = None
    published_at: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    snippet: str = ""  # short excerpt only (no full copyrighted text)
    hash: str = ""
    relevance_score: float = 0.0
    credibility_notes: str = ""


ClaimStatus = Literal["supported", "partly_supported", "contradicted", "not_verified", "opinion"]


class Claim(BaseModel):
    id: str = ""
    claim_text: str
    claim_type: Literal["fact", "opinion", "marketing", "speculation"] = "fact"
    status: ClaimStatus = "not_verified"
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = ""


class ClaimAnalysis(BaseModel):
    claims: list[Claim]


class ReportSection(BaseModel):
    title: str
    body: str
    citations: list[str] = Field(default_factory=list)  # evidence ids
    label: Literal["source_backed", "interpretation", "opinion", "speculation"] = "source_backed"


class GlossaryEntry(BaseModel):
    term: str
    definition: str


class ResearchReport(BaseModel):
    sections: list[ReportSection]
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    model_version: str = ""
    prompt_version: str = ""


class ContentDraft(BaseModel):
    format: str
    tone: str = "professional"
    draft_text: str
    revision: int = 1
    source_claim_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class DraftSet(BaseModel):
    drafts: list[ContentDraft]


class QualityIssue(BaseModel):
    severity: Literal["info", "warning", "error"]
    code: str
    message: str


class QualityReport(BaseModel):
    passed: bool = True
    issues: list[QualityIssue] = Field(default_factory=list)
    independent_categories: int = 0


class JobEvent(BaseModel):
    stage: str
    event_type: Literal["start", "done", "warning", "error", "info"] = "info"
    message: str = ""
    timestamp: datetime = Field(default_factory=utcnow)
    metadata: dict = Field(default_factory=dict)  # never put secrets here


class VoiceProfile(BaseModel):
    style_rules: list[str] = Field(default_factory=list)
    example_texts: list[str] = Field(default_factory=list)  # only content the user permits us to use


CONTENT_FORMATS = ["linkedin", "x_thread", "instagram_caption", "reel_script", "carousel", "hooks", "cta"]
