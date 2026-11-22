"""Parallel research fan-out and the join/normalise step."""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

from packages.agent.nodes.intake_extract import ev
from packages.agent.schemas.models import EvidenceSource, ResearchQuery
from packages.agent.tools.resilience import scrub, with_retries
from packages.providers.search.base import ProviderError, to_evidence

DEPTH_QUERIES = {"quick": 1, "standard": 2, "deep": 3}


def make_search_node(platform: str):
    async def node(state, deps):
        s = deps.settings
        provider = deps.search.get(platform)
        queries = state["plan"].queries[: min(DEPTH_QUERIES.get(state.get("depth", "standard"), 2),
                                              s.max_queries_per_platform)]
        sem = asyncio.Semaphore(2)

        async def one(q: str):
            async with sem:
                try:
                    res = await with_retries(lambda: provider.search(q, s.max_results_per_query),
                                             attempts=s.search_retries, timeout_s=s.search_timeout_s)
                    used = getattr(provider, "last_used", "") or provider.name
                    return q, [to_evidence(r, platform) for r in res], used, None
                except (ProviderError, TimeoutError, Exception) as e:  # noqa: BLE001
                    return q, [], "", scrub(f"{type(e).__name__}: {e}")

        if provider is None:
            return {"events": [ev(f"research:{platform}", "warning", "No provider configured; skipped")]}
        # Hard budget for the whole stage: a hung provider can never block the job. Unfinished queries are
        # cancelled and reported; finished ones are kept.
        budget = float(os.getenv("SEARCH_STAGE_BUDGET_S", "45"))
        tasks = [asyncio.create_task(one(q)) for q in queries]
        done, pending = await asyncio.wait(tasks, timeout=budget)
        for t in pending:
            t.cancel()
        results = [t.result() for t in tasks if t in done]
        cands, log, events = [], [], []
        if pending:
            events.append(ev(f"research:{platform}", "warning",
                             f"{len(pending)} search(es) timed out after {int(budget)}s and were skipped"))
        for q, items, used, err in results:
            log.append(ResearchQuery(platform=platform, query_text=q, result_count=len(items), provider=used, error=err))
            cands.extend(items)
            if err:
                events.append(ev(f"research:{platform}", "warning", f"Query failed after retries: {err}", query=q))
        events.append(ev(f"research:{platform}", "done" if cands else "warning",
                         f"{len(cands)} candidates from {len(queries)} queries"))
        return {"candidates": cands, "queries_log": log, "events": events}

    return node


_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "it", "this", "that", "how"}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP and len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _freshness(published: str | None) -> float:
    if not published:
        return 0.4
    m = re.search(r"(20\d{2})", published)
    if not m:
        return 0.4
    age = max(0, datetime.now(timezone.utc).year - int(m.group(1)))
    return max(0.1, 1.0 - 0.25 * age)


def rank_and_dedupe(candidates: list[EvidenceSource], topic_terms: set[str], limit: int) -> list[EvidenceSource]:
    seen_hash, kept = set(), []
    for c in candidates:
        if c.hash in seen_hash:
            continue
        # semantic-ish dedupe: near-identical titles from the same platform
        ct = tokens(c.title)
        if any(k.platform == c.platform and jaccard(ct, tokens(k.title)) > 0.85 for k in kept):
            continue
        seen_hash.add(c.hash)
        rel = jaccard(tokens(c.title + " " + c.snippet), topic_terms) if topic_terms else 0.0
        c.relevance_score = round(0.7 * min(1.0, rel * 4) + 0.3 * _freshness(c.published_at), 3)
        kept.append(c)
    kept.sort(key=lambda c: c.relevance_score, reverse=True)
    # diversity: round-robin across platforms so one source type cannot crowd out the rest
    by_platform: dict[str, list[EvidenceSource]] = {}
    for c in kept:
        by_platform.setdefault(c.platform, []).append(c)
    out: list[EvidenceSource] = []
    while len(out) < limit and any(by_platform.values()):
        for p in list(by_platform):
            if by_platform[p] and len(out) < limit:
                out.append(by_platform[p].pop(0))
    for i, c in enumerate(out, 1):
        c.id = f"E{i}"
    return out


async def normalize(state, deps):
    plan = state["plan"]
    terms = tokens(" ".join([plan.topic, *plan.entities, *plan.queries]))
    evidence = rank_and_dedupe(state.get("candidates", []), terms, deps.settings.max_evidence)
    platforms = {e.platform for e in evidence}
    low = len(evidence) < 3 or len(platforms) < 2
    events = [ev("normalize", "done", f"{len(evidence)} evidence sources from {len(platforms)} categories "
                                      f"(from {len(state.get('candidates', []))} candidates)")]
    if low:
        events.append(ev("normalize", "warning", "Low evidence: report will say so and avoid strong claims"))
    return {"evidence": evidence, "low_evidence": low, "events": events}
