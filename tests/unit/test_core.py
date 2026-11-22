import json

import pytest

from packages.agent.nodes.analysis import validate_claims
from packages.agent.nodes.creator import longest_shared_run
from packages.agent.nodes.research import rank_and_dedupe, tokens
from packages.agent.schemas.models import Claim, EvidenceSource
from packages.agent.tools.resilience import scrub, with_retries
from packages.providers.extraction.url_safety import UnsafeURL, detect_platform, validate_url
from packages.providers.llm.base import LLM, LLMError, extract_json
from packages.agent.schemas.models import ResearchPlan


# ---- SSRF / URL validation -------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://10.0.0.5/x", "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "ftp://example.com/a", "file:///etc/passwd",
    "javascript:alert(1)", "http://user:pw@example.com/", "http://foo.internal/", "", "http:///nohost",
])
def test_unsafe_urls_blocked(url):
    with pytest.raises(UnsafeURL):
        validate_url(url, resolve=False)


def test_safe_url_ok():
    assert validate_url("https://example.com/a?b=1", resolve=False).startswith("https://example.com")


def test_platform_detection():
    assert detect_platform("https://www.instagram.com/reel/abc").value == "instagram"
    assert detect_platform("https://youtu.be/xyz").value == "youtube"
    assert detect_platform("https://twitter.com/a/status/1").value == "x"
    assert detect_platform("https://evilinstagram.com/x").value == "web"  # suffix spoofing


# ---- LLM JSON repair --------------------------------------------------------
class Flaky(LLM):
    name, model = "flaky", "f"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    async def _complete(self, system, prompt, *, fast):
        self.calls += 1
        return self.replies.pop(0)


@pytest.mark.asyncio
async def test_llm_repairs_malformed_json():
    good = json.dumps({"topic": "t"})
    llm = Flaky(["not json at all", '{"topic": 5, "queries": "x"}', f"```json\n{good}\n```"])
    plan = await llm.generate_json(task="t", system="s", prompt="p", schema=ResearchPlan)
    assert plan.topic == "t" and llm.calls == 3


@pytest.mark.asyncio
async def test_llm_gives_up_after_repairs():
    llm = Flaky(["bad"] * 5)
    with pytest.raises(LLMError):
        await llm.generate_json(task="t", system="s", prompt="p", schema=ResearchPlan)


def test_extract_json_with_chatter():
    assert json.loads(extract_json('Sure! {"a": 1} hope that helps')) == {"a": 1}


# ---- retries / secrets ------------------------------------------------------
@pytest.mark.asyncio
async def test_retries_then_success():
    n = {"c": 0}

    async def fn():
        n["c"] += 1
        if n["c"] < 3:
            raise RuntimeError("boom")
        return "ok"

    assert await with_retries(fn, attempts=2, timeout_s=1, base_delay_s=0) == "ok"


@pytest.mark.asyncio
async def test_timeout_raises():
    import asyncio

    async def slow():
        await asyncio.sleep(1)

    with pytest.raises(asyncio.TimeoutError):
        await with_retries(slow, attempts=0, timeout_s=0.05)


def test_scrub_hides_keys():
    assert "SECRET123" not in scrub("GET https://x/y?key=SECRET123&q=1")


# ---- evidence ranking / dedupe ---------------------------------------------
def _ev(url, title, platform, h=None):
    return EvidenceSource(url=url, title=title, platform=platform, snippet=title, hash=h or url)


def test_dedupe_and_diversity():
    cands = [_ev(f"https://a.com/{i}", f"Example tool review {i}x", "web") for i in range(6)]
    cands += [_ev("https://a.com/0", "dup", "web", h="https://a.com/0"),
              _ev("https://r.com/1", "Example tool reddit thread", "reddit"),
              _ev("https://y.com/1", "Example tool youtube demo", "youtube")]
    out = rank_and_dedupe(cands, tokens("example tool"), 4)
    assert len({e.platform for e in out}) == 3  # round-robin keeps all platforms
    assert [e.id for e in out] == ["E1", "E2", "E3", "E4"]
    assert len({e.hash for e in out}) == len(out)


# ---- claim guardrails -------------------------------------------------------
def test_invented_citations_dropped_and_downgraded():
    evid = {"E1": _ev("https://a.com/1", "t", "web")}
    c = Claim(id="C1", claim_text="x", status="supported", confidence=0.9, evidence_ids=["E1", "E99"])
    validate_claims([c], {"E1"}, evid)
    assert c.evidence_ids == ["E1"]
    assert c.status == "partly_supported"  # one source is never 'supported'
    c2 = Claim(id="C2", claim_text="y", status="contradicted", confidence=0.9, evidence_ids=["E42"])
    validate_claims([c2], {"E1"}, evid)
    assert c2.status == "not_verified" and c2.evidence_ids == []


def test_two_independent_domains_stay_supported():
    evid = {"E1": _ev("https://a.com/1", "t", "web"), "E2": _ev("https://b.org/1", "t", "news")}
    c = Claim(id="C1", claim_text="x", status="supported", confidence=0.8, evidence_ids=["E1", "E2"])
    validate_claims([c], {"E1", "E2"}, evid)
    assert c.status == "supported"


# ---- originality ------------------------------------------------------------
def test_shared_run():
    src = "this new tool lets anyone build agents in minutes without writing any code at all"
    assert longest_shared_run("Wow: lets anyone build agents in minutes without writing any code", src) >= 8
    assert longest_shared_run("A fresh take on no-code automation for teams", src) < 4
