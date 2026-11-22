"""Offline search providers for tests and demo mode. Results are clearly labelled as mock data."""
from __future__ import annotations

from packages.providers.search.base import FallbackChain, ProviderError, RawResult, SearchProvider


class MockSearch(SearchProvider):
    def __init__(self, platform: str, *, fail: bool = False, results: list[RawResult] | None = None):
        self.platform, self.fail = platform, fail
        self.name = f"mock_{platform}"
        self._results = results

    async def search(self, query, limit):
        if self.fail:
            raise ProviderError(f"{self.name} simulated outage")
        if self._results is not None:
            return self._results[:limit]
        host = {"youtube": "www.youtube.com/watch?v=", "reddit": "www.reddit.com/r/mock/comments/",
                "x": "x.com/mock/status/", "news": "news.example.org/", "web": "docs.example.com/"}[self.platform]
        return [RawResult(url=f"https://{host}{self.platform}{i}", title=f"[MOCK] {query} ({self.platform} {i})",
                          snippet=f"Mock snippet about {query} from {self.platform}.", published_at="2026-11-01")
                for i in range(limit)]


def mock_registry() -> dict[str, SearchProvider]:
    return {p: FallbackChain([MockSearch(p)]) for p in ("youtube", "reddit", "x", "news", "web")}
