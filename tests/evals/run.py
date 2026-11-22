"""Run the 20 eval cases and write docs/eval_results.md.

    USE_MOCK=1 python -m tests.evals.run      # offline: validates pipeline behaviour, NOT model quality
    USE_MOCK=0 python -m tests.evals.run      # real run: needs Ollama + search keys; adds latency and quality notes

Metrics: outcome match, citation validity (all cited ids resolve), source categories, drafts count,
copy-check pass, latency. Model-quality metrics (claim accuracy) need manual labelling: see docs/evaluation.md.
"""
from __future__ import annotations

import asyncio
import socket
import statistics
import time
from pathlib import Path

from packages.agent.graph import Deps, build_graph, run_job
from packages.config import get_settings
from packages.providers.llm.factory import build_llm
from packages.providers.search.base import FallbackChain, build_registry
from packages.providers.search.mock import MockSearch
from tests.evals.cases import CASES

HTML = ('<html><head><title>Post</title></head><body><article><p>Body about a tool '
        + "word " * 80 + "</p></article></body></html>")


async def blocked(url):
    raise PermissionError("HTTP 403")


async def ok_html(url):
    return url, "text/html", HTML


async def run_case(case, settings, llm):
    registry = build_registry(settings)
    fetcher = blocked
    initial = {"input_url": case.get("url"), "pasted_text": case.get("text"), "tone": "professional", "depth": "quick",
               "formats": ["linkedin", "x_thread", "instagram_caption", "reel_script"],
               "events": [], "candidates": [], "queries_log": []}
    if case["kind"] == "outage":
        registry = {p: FallbackChain([MockSearch(p, fail=True)]) for p in ("youtube", "reddit", "x", "news", "web")}
    if case["kind"] == "url_ok_html":
        fetcher = ok_html
    t0 = time.perf_counter()
    st = await run_job(build_graph(Deps(llm, registry, settings, fetcher=fetcher)), initial)
    dt = time.perf_counter() - t0
    ev_ids = {e.id for e in st.get("evidence", [])}
    report = st.get("report")
    cites_ok = True if not report else all(c in ev_ids for s in report.sections for c in s.citations)
    q = st.get("quality")
    ok = st["status"] == case["expect"] and cites_ok
    if case.get("flag_injection"):
        ok = ok and st.get("injection_flagged", False)
    return dict(id=case["id"], kind=case["kind"], expect=case["expect"], got=st["status"], ok=ok, cites_ok=cites_ok,
                categories=q.independent_categories if q else 0, drafts=len(st.get("drafts", [])),
                claims=len(st.get("claims", [])), seconds=round(dt, 2))


async def main():
    settings = get_settings()
    # offline runs must not need real DNS for placeholder hostnames
    if settings.use_mock:
        socket.getaddrinfo = lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", p or 80))]
    llm = build_llm(settings)
    rows = [await run_case(c, settings, llm) for c in CASES]
    passed = sum(r["ok"] for r in rows)
    lat = [r["seconds"] for r in rows]
    out = ["# Evaluation results", "",
           f"Mode: {'MOCK (pipeline behaviour only, not model quality)' if settings.use_mock else 'LIVE'}; "
           f"model: {llm.describe()}", "",
           f"**{passed}/{len(rows)} cases matched expected outcome.** Median latency {statistics.median(lat):.2f}s.", "",
           "| # | kind | expected | got | ok | citations valid | source categories | drafts | claims | s |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    out += [f"| {r['id']} | {r['kind']} | {r['expect']} | {r['got']} | {'PASS' if r['ok'] else 'FAIL'} | "
            f"{r['cites_ok']} | {r['categories']} | {r['drafts']} | {r['claims']} | {r['seconds']} |" for r in rows]
    path = Path("docs/eval_results.md")
    path.write_text("\n".join(out) + "\n")
    print("\n".join(out))
    raise SystemExit(0 if passed == len(rows) else 1)


if __name__ == "__main__":
    asyncio.run(main())
