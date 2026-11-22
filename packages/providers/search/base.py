"""Search provider interface, concrete providers, and fallback chains per platform."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from packages.agent.schemas.models import EvidenceSource
from packages.config import Settings


class ProviderError(Exception):
    pass


class RawResult(BaseModel):
    url: str
    title: str
    snippet: str = ""
    author: str | None = None
    published_at: str | None = None


def to_evidence(r: RawResult, platform: str) -> EvidenceSource:
    return EvidenceSource(
        url=r.url, title=r.title.strip()[:300], platform=platform, author=r.author,
        published_at=r.published_at, snippet=r.snippet.strip()[:400],  # short excerpt only
        hash=hashlib.sha1(canonical_url(r.url).encode()).hexdigest()[:16],
    )


def canonical_url(url: str) -> str:
    p = urlparse(url)
    host = (p.hostname or "").removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}"


class SearchProvider(ABC):
    name: str = "provider"

    @abstractmethod
    async def search(self, query: str, limit: int) -> list[RawResult]: ...


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str, *, topic: str = "general", site: str | None = None):
        self.api_key, self.topic, self.site = api_key, topic, site

    async def search(self, query, limit):
        q = f"{query} site:{self.site}" if self.site else query
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post("https://api.tavily.com/search", json={
                    "api_key": self.api_key, "query": q, "max_results": limit, "topic": self.topic})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"tavily {type(e).__name__}") from e
        return [RawResult(url=i["url"], title=i.get("title", ""), snippet=i.get("content", ""),
                          published_at=i.get("published_date")) for i in r.json().get("results", [])]


class BraveProvider(SearchProvider):
    name = "brave"

    def __init__(self, api_key: str, *, site: str | None = None, news: bool = False):
        self.api_key, self.site, self.news = api_key, site, news

    async def search(self, query, limit):
        q = f"{query} site:{self.site}" if self.site else query
        path = "news" if self.news else "web"
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"https://api.search.brave.com/res/v1/{path}/search", params={"q": q, "count": limit},
                                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"brave {type(e).__name__}") from e
        data = r.json()
        items = data.get("results", []) if self.news else data.get("web", {}).get("results", [])
        return [RawResult(url=i["url"], title=i.get("title", ""), snippet=i.get("description", ""),
                          published_at=i.get("age")) for i in items]


class YouTubeProvider(SearchProvider):
    name = "youtube_data_api"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query, limit):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://www.googleapis.com/youtube/v3/search", params={
                    "part": "snippet", "q": query, "type": "video", "maxResults": limit, "key": self.api_key})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"youtube {type(e).__name__}") from e  # never include the URL (contains key)
        return [RawResult(url=f"https://www.youtube.com/watch?v={i['id']['videoId']}",
                          title=i["snippet"]["title"], snippet=i["snippet"].get("description", ""),
                          author=i["snippet"].get("channelTitle"), published_at=i["snippet"].get("publishedAt"))
                for i in r.json().get("items", []) if i.get("id", {}).get("videoId")]


class RedditProvider(SearchProvider):
    """Public JSON search. Reddit often blocks unauthenticated traffic; the chain then falls back to web search."""
    name = "reddit_public"

    async def search(self, query, limit):
        try:
            async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "ResearchCreatorAgent/0.1"}) as c:
                r = await c.get("https://www.reddit.com/search.json", params={"q": query, "limit": limit, "sort": "relevance"})
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"reddit {type(e).__name__}") from e
        out = []
        for ch in r.json().get("data", {}).get("children", []):
            d = ch["data"]
            out.append(RawResult(url=f"https://www.reddit.com{d['permalink']}", title=d.get("title", ""),
                                 snippet=(d.get("selftext") or "")[:400], author=d.get("author"),
                                 published_at=str(d.get("created_utc"))))
        return out


class GdeltNewsProvider(SearchProvider):
    """GDELT DOC 2.0 API: free, keyless news discovery."""
    name = "gdelt"

    async def search(self, query, limit):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://api.gdeltproject.org/api/v2/doc/doc", params={
                    "query": query, "mode": "artlist", "format": "json", "maxrecords": limit, "sort": "hybridrel"})
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"gdelt {type(e).__name__}") from e
        return [RawResult(url=a["url"], title=a.get("title", ""), snippet=a.get("domain", ""),
                          published_at=a.get("seendate")) for a in data.get("articles", [])]


class FallbackChain(SearchProvider):
    """Try providers in order; the first that returns without error wins. Records which one answered."""

    def __init__(self, providers: list[SearchProvider]):
        self.providers = providers
        self.name = "+".join(p.name for p in providers) or "none"
        self.last_used = ""
        self.errors: list[str] = []

    async def search(self, query, limit):
        self.errors = []
        for p in self.providers:
            try:
                res = await p.search(query, limit)
                self.last_used = p.name
                return res
            except ProviderError as e:
                self.errors.append(str(e))
        raise ProviderError("all providers failed: " + "; ".join(self.errors) if self.errors else "no provider configured")


def build_registry(s: Settings) -> dict[str, SearchProvider]:
    """platform -> provider chain. Documented fallbacks:
    youtube: Data API -> web search (site:youtube.com)
    reddit:  public JSON -> web search (site:reddit.com)
    x:       web search (site:x.com) only; the X API is paid, so coverage is best-effort
    news:    GDELT -> Brave news / Tavily news
    web:     Tavily -> Brave
    """
    if s.use_mock:
        from packages.providers.search.mock import mock_registry
        return mock_registry()

    def web(site: str | None = None) -> list[SearchProvider]:
        chain: list[SearchProvider] = []
        if s.tavily_api_key:
            chain.append(TavilyProvider(s.tavily_api_key, site=site))
        if s.brave_api_key:
            chain.append(BraveProvider(s.brave_api_key, site=site))
        return chain

    yt = ([YouTubeProvider(s.youtube_api_key)] if s.youtube_api_key else []) + web("youtube.com")
    news_fallback: list[SearchProvider] = []
    if s.brave_api_key:
        news_fallback.append(BraveProvider(s.brave_api_key, news=True))
    if s.tavily_api_key:
        news_fallback.append(TavilyProvider(s.tavily_api_key, topic="news"))
    return {
        "youtube": FallbackChain(yt),
        "reddit": FallbackChain([RedditProvider(), *web("reddit.com")]),
        "x": FallbackChain(web("x.com")),
        "news": FallbackChain([GdeltNewsProvider(), *news_fallback]),
        "web": FallbackChain(web()),
    }
