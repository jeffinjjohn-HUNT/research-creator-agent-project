"""Source extraction using only public, permitted access. Never pretends to have read inaccessible content."""
from __future__ import annotations

import html
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from packages.agent.schemas.models import ExtractionStatus, OriginalSource, Platform
from packages.providers.extraction.url_safety import UnsafeURL, detect_platform, validate_url

MAX_BYTES = 1_000_000
MAX_REDIRECTS = 3
UA = "ResearchCreatorAgent/0.1 (+public-metadata-only)"

# (url) -> (final_url, content_type, body_text). Injectable for tests.
Fetcher = Callable[[str], Awaitable[tuple[str, str, str]]]


async def safe_fetch(url: str) -> tuple[str, str, str]:
    """GET with SSRF validation on every redirect hop, size cap and text-only content types."""
    current = validate_url(url)
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": UA}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            async with client.stream("GET", current) as r:
                if r.is_redirect:
                    current = validate_url(urljoin(current, r.headers.get("location", "")))
                    continue
                if r.status_code in (401, 403, 429) or r.status_code >= 400:
                    raise PermissionError(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if not (ctype.startswith("text/") or ctype in {"application/xhtml+xml", "application/json"}):
                    raise ValueError(f"unsupported content type {ctype!r}")
                buf = b""
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        break
                return current, ctype, buf[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
    raise UnsafeURL("too many redirects")


_META = re.compile(r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)["\']', re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def parse_meta(page: str) -> dict[str, str]:
    meta = {k.lower(): html.unescape(v) for k, v in _META.findall(page)}
    t = _TITLE.search(page)
    if t:
        meta.setdefault("title", html.unescape(t.group(1)).strip())
    return meta


def _article_text(page: str) -> str:
    try:
        import trafilatura

        return trafilatura.extract(page, include_comments=False, include_tables=False) or ""
    except Exception:
        return ""


LOGIN_WALLED = {Platform.instagram, Platform.tiktok, Platform.x, Platform.linkedin}


async def extract_source(url: str | None, pasted_text: str | None, fetcher: Fetcher = safe_fetch) -> OriginalSource:
    # 1) user-provided text always wins: it is permitted content and fully readable
    if pasted_text and pasted_text.strip():
        platform = detect_platform(url) if url else Platform.pasted
        return OriginalSource(url=url, platform=platform, extracted_text=pasted_text.strip()[:20000],
                              extraction_status=ExtractionStatus.ok, confidence="user_provided",
                              note="Text supplied by the user.")
    if not url:
        return OriginalSource(note="No URL or text provided.")

    platform = detect_platform(url)
    try:
        final_url, _ctype, page = await fetcher(url)
    except (UnsafeURL, PermissionError, ValueError, httpx.HTTPError, TimeoutError) as e:
        return OriginalSource(url=url, platform=platform, extraction_status=ExtractionStatus.inaccessible,
                              note=f"Could not read the page ({type(e).__name__}). Please paste the caption, "
                                   "transcript or text, or upload a screenshot.")

    meta = parse_meta(page)
    title = meta.get("og:title") or meta.get("twitter:title") or meta.get("title")
    desc = meta.get("og:description") or meta.get("description") or ""
    creator = meta.get("author") or meta.get("og:site_name")

    if platform in LOGIN_WALLED or platform == Platform.youtube:
        # Public metadata only. Captions/transcripts are not fetched without permission.
        text = " ".join(x for x in (title, desc) if x).strip()
        generic = (title or "").lower() in {"instagram", "tiktok", "x", "linkedin", "log in", "login"}
        if not text or generic:
            return OriginalSource(url=final_url, platform=platform, extraction_status=ExtractionStatus.inaccessible,
                                  note=f"{platform.value} did not expose readable public content (login wall). "
                                       "Please paste the caption/transcript or upload a screenshot.")
        return OriginalSource(url=final_url, platform=platform, title=title, creator=creator, extracted_text=text,
                              extraction_status=ExtractionStatus.partial, confidence="low",
                              note="Only public title/description were available; no transcript was read.")

    body = _article_text(page) or desc
    if not body.strip():
        return OriginalSource(url=final_url, platform=platform, title=title,
                              extraction_status=ExtractionStatus.inaccessible,
                              note="Page returned no extractable article text (JS-rendered or paywalled). "
                                   "Please paste the text.")
    return OriginalSource(url=final_url, platform=platform, title=title, creator=creator,
                          posted_at=meta.get("article:published_time"), extracted_text=body[:20000],
                          extraction_status=ExtractionStatus.ok, confidence="high")
