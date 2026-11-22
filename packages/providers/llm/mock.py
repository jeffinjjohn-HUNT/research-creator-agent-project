"""Deterministic offline LLM used for tests and the no-network demo mode (USE_MOCK=1).

It answers per `task` and reads real evidence ids / claim ids out of the prompt, so the
downstream validation and citation-checking code is exercised for real.
"""
from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

from packages.agent.schemas.models import (
    Claim,
    ClaimAnalysis,
    ClaimDraft,
    ContentDraft,
    DraftSet,
    GlossaryEntry,
    ReportSection,
    ResearchPlan,
    ResearchReport,
)
from packages.providers.llm.base import LLM

T = TypeVar("T", bound=BaseModel)


class MockLLM(LLM):
    name = "mock"
    model = "mock-1"

    async def _complete(self, system: str, prompt: str, *, fast: bool, schema=None) -> str:  # pragma: no cover
        raise NotImplementedError

    async def generate_json(self, *, task, system, prompt, schema, fast=False, budget_s=None):
        if task == "parse_plan":
            return ResearchPlan(
                topic="Example AI tool",
                entities=["ExampleTool"],
                claims=[
                    ClaimDraft(text="ExampleTool is free to use", claim_type="marketing"),
                    ClaimDraft(text="ExampleTool runs locally on a laptop", claim_type="fact"),
                    ClaimDraft(text="It will replace developers", claim_type="speculation"),
                ],
                key_questions=["What is ExampleTool?", "How do I set it up?"],
                queries=["ExampleTool review", "ExampleTool tutorial", "ExampleTool alternatives"],
            )  # type: ignore[return-value]
        ev_ids = re.findall(r"\[(E\d+)\]", prompt)
        if task == "claim_analysis":
            claim_texts = re.findall(r"^CLAIM (C\d+): (.+)$", prompt, re.M)
            claims = []
            for i, (cid, text) in enumerate(claim_texts):
                ids = ev_ids[i : i + 2] if ev_ids else []
                claims.append(
                    Claim(
                        id=cid,
                        claim_text=text,
                        status="supported" if ids and i == 0 else ("partly_supported" if ids else "not_verified"),
                        confidence=0.6 if ids else 0.0,
                        evidence_ids=ids,
                        explanation="Mock analysis based on retrieved snippets.",
                    )
                )
            return ClaimAnalysis(claims=claims)  # type: ignore[return-value]
        if task == "synthesize_section":
            title = re.search(r"^SECTION: (.+)$", prompt, re.M).group(1)
            return ReportSection(title=title, body=f"Mock summary for '{title}'.", citations=ev_ids[:2])  # type: ignore[return-value]
        if task == "glossary":
            return schema(terms=[GlossaryEntry(term="LLM", definition="Large language model.")])
        if task == "content_one":
            f = re.search(r"^FORMAT: (\S+)$", prompt, re.M).group(1)
            return schema(draft_text=f"Original mock {f} draft about a new AI tool.")
        if task == "synthesize":
            cite = ev_ids[:2]
            titles = ["What it is", "Beginner explainer", "Technical deep dive", "Why it matters", "How it works",
                      "Setup and prerequisites", "Use cases and examples", "Pros, cons and risks",
                      "Alternatives", "Beginner roadmap", "Perspectives"]
            return ResearchReport(
                sections=[
                    ReportSection(title=t, body=f"Mock summary for '{t}'.", citations=cite if cite else [])
                    for t in titles
                ],
                glossary=[GlossaryEntry(term="LLM", definition="Large language model.")],
            )  # type: ignore[return-value]
        if task == "content":
            fmts = re.findall(r"^FORMAT: (\S+)$", prompt, re.M)
            claim_ids = re.findall(r"^CLAIM (C\d+):", prompt, re.M)[:2]
            return DraftSet(
                drafts=[
                    ContentDraft(format=f, draft_text=f"Original mock {f} draft about a new AI tool.",
                                 source_claim_ids=claim_ids)
                    for f in fmts
                ]
            )  # type: ignore[return-value]
        raise ValueError(f"MockLLM: unknown task {task}")
