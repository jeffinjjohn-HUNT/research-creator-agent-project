"""Typed graph state. List fields written by parallel nodes use an additive reducer."""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from packages.agent.schemas.models import (
    Claim,
    ContentDraft,
    EvidenceSource,
    JobEvent,
    OriginalSource,
    QualityReport,
    ResearchPlan,
    ResearchQuery,
    ResearchReport,
    VoiceProfile,
)


class JobState(TypedDict, total=False):
    # inputs
    job_id: str
    input_url: str | None
    user_note: str
    pasted_text: str | None
    formats: list[str]
    tone: str
    depth: str  # quick | standard | deep
    voice: VoiceProfile | None

    # derived
    platform: str
    original: OriginalSource
    plan: ResearchPlan
    candidates: Annotated[list[EvidenceSource], operator.add]  # written by parallel search nodes
    queries_log: Annotated[list[ResearchQuery], operator.add]
    events: Annotated[list[JobEvent], operator.add]
    evidence: list[EvidenceSource]
    claims: list[Claim]
    report: ResearchReport
    drafts: list[ContentDraft]
    quality: QualityReport
    low_evidence: bool
    injection_flagged: bool

    # outcome
    status: str  # running | needs_input | failed | completed | completed_with_warnings
    error: str | None
