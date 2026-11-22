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

    async def _complete(self, system, prompt, *, fast, schema=None):
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


@pytest.mark.asyncio
async def test_llm_call_budget_raises_instead_of_hanging():
    import asyncio

    class Slow(LLM):
        name, model = "slow", "s"

        async def _complete(self, system, prompt, *, fast, schema=None):
            await asyncio.sleep(100)

    with pytest.raises(LLMError, match="did not answer"):
        await Slow().generate_json(task="t", system="s", prompt="p", schema=ResearchPlan, budget_s=0.2)


@pytest.mark.asyncio
async def test_ollama_sends_schema_and_falls_back_on_400():
    import json as _json, threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from packages.providers.llm.base import OllamaLLM
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = _json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append(body["format"])
            if isinstance(body["format"], dict):   # simulate an Ollama that rejects schema formats
                self.send_response(400); self.end_headers(); return
            out = _json.dumps({"message": {"content": '{"topic":"ok"}'}}).encode()
            self.send_response(200); self.send_header("content-type", "application/json"); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8998), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        plan = await OllamaLLM("http://127.0.0.1:8998", "m", "m", 30, 0.2).generate_json(
            task="t", system="s", prompt="p", schema=ResearchPlan)
    finally:
        srv.shutdown()
    assert plan.topic == "ok" and isinstance(seen[0], dict) and seen[1] == "json"


def test_heuristic_links_claim_to_matching_sources_only():
    from packages.agent.nodes.analysis import heuristic_link
    from packages.agent.schemas.models import Claim, EvidenceSource
    ev = [EvidenceSource(id="E1", url="https://a.org/x", title="RAG explained", platform="news",
                         snippet="Retrieval-augmented generation lets a model look up relevant documents before answering"),
          EvidenceSource(id="E2", url="https://b.org/y", title="Cooking", platform="web", snippet="Boil pasta for ten minutes")]
    c = Claim(id="C1", claim_text="RAG lets a model look up relevant documents before answering")
    other = Claim(id="C2", claim_text="Quantum toasters outsell phones")
    assert heuristic_link([c, other], ev) == 1
    assert c.evidence_ids == ["E1"] and c.status == "partly_supported"
    assert other.evidence_ids == [] and other.status == "not_verified"


def test_attributed_claims_are_checked_on_their_content():
    from packages.agent.nodes.analysis import heuristic_link
    from packages.agent.schemas.models import Claim, EvidenceSource
    ev = [EvidenceSource(id="E1", url="https://a.org/x", title="t", platform="web",
                         snippet="RAG reduces made-up answers and lets companies use private data without retraining")]
    c = Claim(id="C1", claim_text="Supporters say RAG reduces made-up answers and lets companies use private data without retraining")
    assert heuristic_link([c], ev) == 1 and c.evidence_ids == ["E1"]
