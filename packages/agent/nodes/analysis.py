from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from pydantic import BaseModel

from packages.agent.nodes.intake_extract import ev
from packages.agent.prompts.v1 import (CLAIMS_SYSTEM, GLOSSARY_SYSTEM, PROMPT_VERSION, REQUIRED_SECTIONS, SECTION_HINTS,
                                       SECTION_SYSTEM, fence)
from packages.agent.schemas.models import Claim, ClaimAnalysis, GlossaryEntry, ReportSection, ResearchReport
from packages.providers.llm.base import LLMError


STOP = set("a an the and or of to in on for with is are was be it its this that as by at from can will not do does "
           "how what why who which their they them you your we our more most than into about over also".split())


class Glossary(BaseModel):
    terms: list[GlossaryEntry]


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP}


def overlap(a: str, b: str) -> float:
    """Share of the words in `a` that also appear in `b` (0..1)."""
    ta = tokens(a)
    return len(ta & tokens(b)) / len(ta) if ta else 0.0


def top_evidence(query: str, evidence, k: int):
    """Evidence most relevant to a query: word overlap blended with the stored relevance score."""
    scored = sorted(evidence, key=lambda e: overlap(query, f"{e.title} {e.snippet}") + 0.5 * (e.relevance_score or 0), reverse=True)
    return scored[:k]


ATTRIB = re.compile(r"^(supporters|critics|proponents|opponents|experts|researchers|developers|people|some)\s+"
                    r"(say|says|argue|argues|note|notes|claim|claims|warn|warns|believe|believes|point out|"
                    r"worry|worries)(\s+that)?\s+", re.I)


def heuristic_link(claims: list[Claim], evidence) -> int:
    """Fallback when the model cited nothing: link a claim to evidence that shares most of its key words.
    Marked as a heuristic in the explanation; never produces more than partly_supported unless 2+ domains agree."""
    n = 0
    for c in claims:
        if c.claim_type == "opinion" or c.evidence_ids:
            continue
        text = ATTRIB.sub("", c.claim_text)  # "Critics note that X" -> check X itself
        ranked = sorted(((overlap(text, f"{e.title} {e.snippet}"), e) for e in evidence), key=lambda x: -x[0])
        hits = [(o, e) for o, e in ranked if o >= 0.5][:3]
        if not hits:
            continue
        c.evidence_ids = [e.id for _, e in hits]
        domains = {urlparse(e.url).hostname for _, e in hits}
        c.status = "supported" if len(domains) >= 2 and hits[0][0] >= 0.7 else "partly_supported"
        c.confidence = round(min(0.75, hits[0][0]), 2)
        c.explanation = "Matched to sources by wording overlap (automatic check, not model judgement)."
        n += 1
    return n


def _evidence_block(evidence) -> str:
    return "\n".join(f"[{e.id}] ({e.platform}, {e.published_at or 'undated'}) {e.title} :: {e.snippet}" for e in evidence)


def validate_claims(claims: list[Claim], known_ids: set[str], evidence_by_id: dict) -> list[Claim]:
    """Deterministic guardrails on top of the LLM's judgement: never trust citations blindly."""
    for c in claims:
        c.evidence_ids = [i for i in dict.fromkeys(c.evidence_ids) if i in known_ids]  # drop invented ids
        if c.claim_type == "opinion":
            c.status = "opinion"
        if c.status in ("supported", "partly_supported", "contradicted") and not c.evidence_ids:
            c.status, c.confidence = "not_verified", 0.0
            c.explanation = (c.explanation + " [downgraded: no valid evidence cited]").strip()
        if c.status == "supported":
            domains = {urlparse(evidence_by_id[i].url).hostname for i in c.evidence_ids}
            if len(domains) < 2:  # a single source is never 'fully supported'
                c.status = "partly_supported"
                c.explanation = (c.explanation + " [downgraded: only one independent source]").strip()
        c.confidence = max(0.0, min(1.0, c.confidence))
    return claims


async def analyze_claims(state, deps):
    plan, evidence = state["plan"], state.get("evidence", [])
    drafts = plan.claims or []
    if not drafts:
        return {"claims": [], "events": [ev("claims", "warning", "No claims were identified in the source")]}
    claims = [Claim(id=f"C{i}", claim_text=d.text, claim_type=d.claim_type) for i, d in enumerate(drafts, 1)]
    if not evidence:
        for c in claims:
            c.status = "opinion" if c.claim_type == "opinion" else "not_verified"
        return {"claims": claims, "events": [ev("claims", "warning", "No evidence retrieved; all claims unverified")]}
    prompt = ("\n".join(f"CLAIM {c.id}: {c.claim_text} (type: {c.claim_type})" for c in claims)
              + "\n\nEvidence:\n" + fence(_evidence_block(evidence)))
    try:
        res = await deps.llm.generate_json(task="claim_analysis", system=CLAIMS_SYSTEM, prompt=prompt,
                                           schema=ClaimAnalysis)
        by_id = {c.id: c for c in res.claims}
        merged = []
        for c in claims:  # keep our ids/text; take only judgement fields from the model
            m = by_id.get(c.id)
            if m:
                c.status, c.confidence, c.evidence_ids, c.explanation = m.status, m.confidence, m.evidence_ids, m.explanation
            merged.append(c)
        claims, msg, kind = merged, "Claims analysed", "done"
    except LLMError as e:
        msg, kind = f"Claim analysis failed; claims left unverified: {e}", "warning"
    by_ev = {e.id: e for e in evidence}
    claims = validate_claims(claims, set(by_ev), by_ev)
    unlinked = [c for c in claims if c.status == "not_verified" and c.claim_type != "opinion"]
    if unlinked and heuristic_link(unlinked, evidence):
        claims = validate_claims(claims, set(by_ev), by_ev)
        msg += " (some claims matched to sources by text overlap)"
    return {"claims": claims, "events": [ev("claims", kind, msg)]}


async def synthesize(state, deps):
    """Write the report one section at a time with only the most relevant evidence in each prompt.
    Small local models do much better on short focused prompts than one huge request."""
    plan, evidence, claims = state["plan"], state.get("evidence", []), state.get("claims", [])
    known = {e.id for e in evidence}
    claim_lines = "\n".join(f"- [{c.status}] {c.claim_text}" for c in claims[:8])
    sem = asyncio.Semaphore(int(__import__("os").getenv("SECTION_CONCURRENCY", "2")))

    async def one(title: str) -> ReportSection | None:
        picks = top_evidence(f"{plan.topic} {title} {SECTION_HINTS[title]}", evidence, 4)
        prompt = (f"Topic: {plan.topic}\nSECTION: {title}\nGoal: {SECTION_HINTS[title]}\n"
                  f"Low evidence overall: {state.get('low_evidence', False)}\nKnown claims:\n{claim_lines or '(none)'}\n\n"
                  f"Evidence:\n" + fence(_evidence_block(picks), 3500))
        try:
            async with sem:
                sec = await deps.llm.generate_json(task="synthesize_section", system=SECTION_SYSTEM, prompt=prompt,
                                                   schema=ReportSection, budget_s=120)
        except LLMError:
            return None
        sec.title = title
        sec.body = re.sub(r"\s*\[E\d+\]", "", sec.body).strip()  # citations belong in the chips, not the prose
        sec.citations = [c for c in dict.fromkeys(sec.citations) if c in {e.id for e in picks}][:3]
        return sec if sec.body.strip() else None

    results = await asyncio.gather(*[one(t) for t in REQUIRED_SECTIONS])
    sections, failed = [], []
    for t, r in zip(REQUIRED_SECTIONS, results):
        if r:
            sections.append(r)
        else:
            failed.append(t)
            sections.append(ReportSection(title=t, label="interpretation",
                                          body="The model could not write this section. See the Sources tab for the raw evidence."))
    glossary: list[GlossaryEntry] = []
    if evidence and len(failed) < len(REQUIRED_SECTIONS):
        try:
            g = await deps.llm.generate_json(task="glossary", system=GLOSSARY_SYSTEM, schema=Glossary, budget_s=90,
                                             prompt=f"Topic: {plan.topic}\nEvidence:\n" + fence(_evidence_block(top_evidence(plan.topic, evidence, 5)), 3000))
            glossary = g.terms[:8]
        except LLMError:
            pass
    report = ResearchReport(sections=sections, glossary=glossary)
    for s_ in report.sections:  # strip any citation that doesn't resolve to a stored source
        s_.citations = [c for c in dict.fromkeys(s_.citations) if c in known]
    report.model_version = deps.llm.model or deps.llm.name
    report.prompt_version = PROMPT_VERSION
    if len(failed) == len(REQUIRED_SECTIONS):
        kind, msg = "error", "Synthesis failed: the model wrote none of the sections"
    elif failed:
        kind, msg = "warning", f"Report written; {len(failed)} section(s) could not be written: {', '.join(failed)}"
    else:
        kind, msg = "done", f"Report written ({len(report.sections)} sections)"
    return {"report": report, "events": [ev("synthesize", kind, msg)]}


def missing_sections(report: ResearchReport) -> list[str]:
    have = {s.title.lower() for s in report.sections}
    return [t for t in REQUIRED_SECTIONS if t.lower() not in have]
