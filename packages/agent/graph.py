"""LangGraph workflow:

intake -> extract -> (needs_input? END) -> plan -> [youtube | reddit | x | news | web] (parallel)
       -> normalize (join) -> claims -> synthesize -> content -> qa -> finalize
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from langgraph.graph import END, START, StateGraph

from packages.agent.nodes.analysis import analyze_claims, synthesize
from packages.agent.nodes.creator import content_studio, finalize, qa
from packages.agent.nodes.intake_extract import extract, intake, route_after_extract, route_after_intake
from packages.agent.nodes.plan import parse_and_plan
from packages.agent.nodes.research import make_search_node, normalize
from packages.agent.state import JobState
from packages.config import Settings
from packages.providers.extraction.extractor import Fetcher, safe_fetch
from packages.providers.llm.base import LLM
from packages.providers.search.base import SearchProvider

PLATFORMS = ["youtube", "reddit", "x", "news", "web"]


@dataclass
class Deps:
    llm: LLM
    search: dict[str, SearchProvider]
    settings: Settings
    fetcher: Fetcher = field(default=safe_fetch)


def build_graph(deps: Deps):
    g = StateGraph(JobState)

    def bind(fn):
        async def node(state):
            return await fn(state, deps)
        node.__name__ = fn.__name__
        return node

    g.add_node("intake", bind(intake))
    g.add_node("extract", bind(extract))
    g.add_node("plan", bind(parse_and_plan))
    for p in PLATFORMS:
        g.add_node(f"research_{p}", partial_node(make_search_node(p), deps))
    g.add_node("normalize", bind(normalize))
    g.add_node("claims", bind(analyze_claims))
    g.add_node("synthesize", bind(synthesize))
    g.add_node("content", bind(content_studio))
    g.add_node("qa", bind(qa))
    g.add_node("finalize", bind(finalize))

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", route_after_intake, {"extract": "extract", "end": END})
    g.add_conditional_edges("extract", route_after_extract, {"plan": "plan", "end": END})
    for p in PLATFORMS:
        g.add_edge("plan", f"research_{p}")  # parallel fan-out
    g.add_edge([f"research_{p}" for p in PLATFORMS], "normalize")  # join: waits for all branches
    for a, b in [("normalize", "claims"), ("claims", "synthesize"), ("synthesize", "content"),
                 ("content", "qa"), ("qa", "finalize"), ("finalize", END)]:
        g.add_edge(a, b)
    return g.compile()


def partial_node(fn, deps):
    async def node(state):
        return await fn(state, deps)
    return node


async def run_job(graph, initial: dict, on_update=None) -> dict:
    """Stream the graph, forwarding each node's real events (no fake progress). Returns the final state."""
    final: dict = dict(initial)
    async for mode, payload in graph.astream(initial, stream_mode=["updates", "values"]):
        if mode == "values":
            final = payload
        elif on_update:
            for node_name, update in payload.items():
                await on_update(node_name, update or {})
    return final
