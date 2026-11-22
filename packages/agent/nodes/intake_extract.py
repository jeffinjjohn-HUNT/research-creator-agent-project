from __future__ import annotations

import re

from packages.agent.prompts.v1 import INJECTION_PATTERNS
from packages.agent.schemas.models import ExtractionStatus, JobEvent, Platform
from packages.providers.extraction.extractor import extract_source
from packages.providers.extraction.url_safety import UnsafeURL, detect_platform, validate_url


def ev(stage, kind, msg, **meta) -> JobEvent:
    return JobEvent(stage=stage, event_type=kind, message=msg, metadata=meta)


async def intake(state, deps):
    url, pasted = (state.get("input_url") or "").strip() or None, state.get("pasted_text")
    if not url and not (pasted and pasted.strip()):
        return {"status": "failed", "error": "Provide a URL or paste the content to research.",
                "events": [ev("intake", "error", "No URL or pasted text")]}
    platform = Platform.pasted
    if url:
        try:
            url = validate_url(url)  # SSRF + scheme checks
            platform = detect_platform(url)
        except UnsafeURL as e:
            if not (pasted and pasted.strip()):
                return {"status": "failed", "error": f"URL rejected: {e}",
                        "events": [ev("intake", "error", f"URL rejected: {e}")]}
            url = None  # fall back to the pasted text alone
    return {"input_url": url, "platform": platform.value, "status": "running",
            "events": [ev("intake", "done", f"Accepted input (platform: {platform.value})")]}


async def extract(state, deps):
    original = await extract_source(state.get("input_url"), state.get("pasted_text"), deps.fetcher)
    events = [ev("extract", "done" if original.extraction_status != ExtractionStatus.inaccessible else "warning",
                 f"Extraction {original.extraction_status.value} ({original.confidence})",
                 note=original.note or "")]
    flagged = any(re.search(p, original.extracted_text, re.I) for p in INJECTION_PATTERNS)
    if flagged:
        events.append(ev("extract", "warning", "Possible prompt-injection text found in source; treated as data only"))
    out = {"original": original, "injection_flagged": flagged, "events": events}
    if original.extraction_status == ExtractionStatus.inaccessible:
        out.update(status="needs_input", error=original.note)
    return out


def route_after_extract(state) -> str:
    return "end" if state.get("status") in ("needs_input", "failed") else "plan"


def route_after_intake(state) -> str:
    return "end" if state.get("status") == "failed" else "extract"
