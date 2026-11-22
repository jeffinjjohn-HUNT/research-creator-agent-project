from __future__ import annotations

from packages.agent.nodes.intake_extract import ev
from packages.agent.prompts.v1 import PLAN_SYSTEM, fence
from packages.agent.schemas.models import ResearchPlan
from packages.providers.llm.base import LLMError


async def parse_and_plan(state, deps):
    o = state["original"]
    prompt = (f"User note: {state.get('user_note') or '(none)'}\nPlatform: {o.platform.value}\n"
              f"Title: {o.title}\nCreator: {o.creator}\nSource text:\n{fence(o.extracted_text, 4000)}")
    try:
        # Planning only needs the gist, so cap the wait; on timeout the fallback plan below keeps the job moving.
        plan = await deps.llm.generate_json(task="parse_plan", system=PLAN_SYSTEM, prompt=prompt,
                                            schema=ResearchPlan, fast=False, budget_s=150)
    except LLMError as e:
        # Fallback branch: degrade to a keyword plan so the pipeline can still research.
        words = (o.title or o.extracted_text)[:120]
        plan = ResearchPlan(topic=words, queries=[words])
        return {"plan": plan, "events": [ev("plan", "warning", f"LLM planning failed, using fallback plan: {e}")]}
    plan.queries = [q.strip() for q in plan.queries if q.strip()][: deps.settings.max_queries_per_platform + 3]
    if not plan.queries:
        plan.queries = [plan.topic]
    return {"plan": plan, "events": [ev("plan", "done", f"Planned {len(plan.queries)} queries, "
                                                         f"{len(plan.claims)} claims identified")]}
