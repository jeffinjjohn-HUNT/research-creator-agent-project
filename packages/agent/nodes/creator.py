from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel

from packages.agent.nodes.analysis import missing_sections
from packages.agent.nodes.intake_extract import ev
from packages.agent.nodes.analysis import top_evidence
from packages.agent.prompts.v1 import DRAFT_SYSTEM, FORMAT_GUIDE, fence
from packages.agent.schemas.models import CONTENT_FORMATS, ContentDraft, QualityIssue, QualityReport
from packages.providers.llm.base import LLMError

NGRAM = 8  # a run of 8+ identical words copied from the source is treated as copying


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def longest_shared_run(a: str, b: str) -> int:
    """Longest run of consecutive identical words shared by two texts (originality check)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0
    index: dict[str, list[int]] = {}
    for j, w in enumerate(wb):
        index.setdefault(w, []).append(j)
    best = 0
    for i, w in enumerate(wa):
        for j in index.get(w, []):
            k = 0
            while i + k < len(wa) and j + k < len(wb) and wa[i + k] == wb[j + k]:
                k += 1
            best = max(best, k)
    return best


class DraftText(BaseModel):
    draft_text: str


async def content_studio(state, deps):
    """One focused LLM call per requested format, each told the format's shape and length."""
    formats = [f for f in (state.get("formats") or ["linkedin", "x_thread", "instagram_caption", "reel_script"])
               if f in CONTENT_FORMATS]
    claims, evidence, plan = state.get("claims", []), state.get("evidence", []), state["plan"]
    voice, tone = state.get("voice"), state.get("tone", "professional")
    usable = [c for c in claims if c.status in ("supported", "partly_supported")] or \
             [c for c in claims if c.claim_type != "opinion" and c.status != "contradicted"]
    use_ids = [c.id for c in usable[:3]]
    facts = "\n".join(f"CLAIM {c.id} [{c.status}]: {c.claim_text}" for c in usable[:5])
    ev_text = "\n".join(f"- {e.title}: {e.snippet}" for e in top_evidence(plan.topic, evidence, 4))
    sem = asyncio.Semaphore(2)

    original = state["original"].extracted_text or ""

    async def one(f: str):
        avoid = ""
        for attempt in range(2):  # second try only if the first copied the source too closely
            d = await attempt_once(f, avoid)
            if d is None or longest_shared_run(d.draft_text, original) < NGRAM:
                return d
            avoid = _copied_phrase(d.draft_text, original)
        return d

    def _copied_phrase(draft: str, src: str) -> str:
        w = _words(draft)
        for i in range(len(w) - NGRAM + 1):
            ph = " ".join(w[i:i + NGRAM])
            if ph in " ".join(_words(src)):
                return ph
        return ""

    async def attempt_once(f: str, avoid: str):
        prompt = (f"FORMAT: {f}\nGuidance: {FORMAT_GUIDE[f]}\nTone: {tone}\n"
                  f"Voice profile: {voice.model_dump_json() if voice else 'none'}\nTopic: {plan.topic}\n"
                  f"Facts you may use:\n{facts or '(none verified)'}\n\nBackground evidence (rephrase, do not copy):\n"
                  + fence(ev_text, 2500)
                  + (f"\nIMPORTANT: your last attempt reused the phrase '{avoid}' from the source. Write it again in "
                     "completely different words." if avoid else "")
                  + f"\nUser note: {fence(state.get('user_note') or '', 500)}")
        try:
            async with sem:
                r = await deps.llm.generate_json(task="content_one", system=DRAFT_SYSTEM, prompt=prompt,
                                                 schema=DraftText, budget_s=120)
        except LLMError:
            return None
        text = r.draft_text.strip()
        return ContentDraft(format=f, tone=tone, draft_text=text, source_claim_ids=use_ids) if text else None

    drafts = [d for d in await asyncio.gather(*[one(f) for f in formats]) if d]
    if not drafts:
        return {"drafts": [], "events": [ev("content", "error", "Content generation failed for every format")]}
    missed = len(formats) - len(drafts)
    note = f" ({missed} format(s) failed)" if missed else ""
    return {"drafts": drafts, "events": [ev("content", "warning" if missed else "done", f"{len(drafts)} drafts generated{note}")]}


async def qa(state, deps):
    issues: list[QualityIssue] = []
    evidence = state.get("evidence", [])
    claims, drafts, report = state.get("claims", []), state.get("drafts", []), state["report"]
    original = state["original"].extracted_text
    ev_ids, claim_ids = {e.id for e in evidence}, {c.id for c in claims}
    categories = len({e.platform for e in evidence})

    if categories < 3:
        issues.append(QualityIssue(severity="warning", code="few_source_categories",
                                   message=f"Only {categories} independent source categories (target: 3+)."))
    if state.get("low_evidence"):
        issues.append(QualityIssue(severity="warning", code="low_evidence", message="Evidence set is thin."))
    if state["original"].extraction_status.value == "partial":
        issues.append(QualityIssue(severity="info", code="partial_source",
                                   message="Original source was only partially readable (no transcript)."))
    if state.get("injection_flagged"):
        issues.append(QualityIssue(severity="info", code="injection_text",
                                   message="Source contained instruction-like text; it was treated as data."))
    for t in missing_sections(report):
        issues.append(QualityIssue(severity="warning", code="missing_section", message=f"Report lacks section: {t}"))
    for s in report.sections:
        bad = [c for c in s.citations if c not in ev_ids]
        if bad:
            issues.append(QualityIssue(severity="error", code="bad_citation", message=f"{s.title}: unknown {bad}"))
        if s.label == "source_backed" and not s.citations and evidence and s.title != "Report unavailable":
            issues.append(QualityIssue(severity="warning", code="uncited_section",
                                       message=f"'{s.title}' is source-backed but cites nothing."))
    for d in drafts:
        bad = [c for c in d.source_claim_ids if c not in claim_ids]
        if bad:
            issues.append(QualityIssue(severity="error", code="bad_claim_ref", message=f"{d.format}: unknown {bad}"))
        run = longest_shared_run(d.draft_text, original)
        if run >= NGRAM:
            issues.append(QualityIssue(severity="error", code="copied_wording",
                                       message=f"{d.format} copies {run} consecutive words from the source."))
        corpus = " ".join([original, " ".join(c.claim_text for c in claims),
                           " ".join(f"{e.title} {e.snippet}" for e in evidence)]).lower()
        names = {m for m in re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", d.draft_text) if m.lower() not in corpus}
        if names:
            issues.append(QualityIssue(severity="warning", code="unsupported_name",
                                       message=f"{d.format} names {sorted(names)} which no source mentions; check before posting."))
        weak = [c for c in d.source_claim_ids if any(x.id == c and x.status in ("not_verified", "contradicted")
                                                     for x in claims)]
        if weak:
            issues.append(QualityIssue(severity="warning", code="unverified_claim_in_draft",
                                       message=f"{d.format} relies on unverified/contradicted claims {weak}."))
    if not drafts:
        issues.append(QualityIssue(severity="warning", code="no_drafts", message="No content drafts were produced."))
    passed = not any(i.severity == "error" for i in issues)
    return {"quality": QualityReport(passed=passed, issues=issues, independent_categories=categories),
            "events": [ev("qa", "done" if passed else "warning", f"QA {'passed' if passed else 'found errors'}: "
                                                                  f"{len(issues)} issue(s)")]}


async def finalize(state, deps):
    q = state["quality"]
    clean = q.passed and not any(i.severity == "warning" for i in q.issues)
    status = "completed" if clean else "completed_with_warnings"
    return {"status": status, "events": [ev("save", "done", f"Job {status}")]}
