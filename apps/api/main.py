"""FastAPI entrypoint. Jobs run in the background; progress is real events persisted per node."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pathlib import Path
from pydantic import BaseModel, Field

from packages.agent.graph import Deps, build_graph, run_job
from packages.agent.schemas.models import CONTENT_FORMATS, VoiceProfile
from packages.config import Settings, get_settings
from packages.db.repository import Repository
from packages.providers.llm.factory import build_llm
from packages.providers.search.base import build_registry
from packages.services.export.markdown import drafts_markdown, report_markdown

RATE_LIMIT, RATE_WINDOW = 10, 60  # job creations per client per minute


class NewJob(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    pasted_text: str | None = Field(default=None, max_length=20000)
    note: str = Field(default="", max_length=1000)
    formats: list[str] = Field(default_factory=lambda: ["linkedin", "x_thread", "instagram_caption", "reel_script"])
    tone: str = Field(default="professional", max_length=40)
    depth: str = Field(default="standard", pattern="^(quick|standard|deep)$")


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    s = settings or get_settings()
    repo = Repository(s.database_path)
    llm = deps.llm if deps else build_llm(s)
    deps = deps or Deps(llm=llm, search=build_registry(s), settings=s)
    graph = build_graph(deps)
    app = FastAPI(title="AI Research & Creator Agent", version="0.1.0")
    hits: dict[str, deque] = defaultdict(deque)
    tasks: set[asyncio.Task] = set()

    async def execute(job_id: str, initial: dict):
        async def on_update(_node: str, update: dict):
            for e in update.get("events", []):
                repo.add_event(job_id, e)

        repo.set_status(job_id, "running")
        try:
            final = await run_job(graph, initial, on_update)
            result = {k: _dump(final.get(k)) for k in ("original", "plan", "evidence", "claims", "report", "drafts",
                                                       "quality", "queries_log")}
            repo.save_result(job_id, final.get("status", "failed"), final.get("error"), result)
        except Exception as e:  # noqa: BLE001 - never leave a job stuck in 'running'
            repo.add_event(job_id, _err_event(e))
            repo.set_status(job_id, "failed", f"{type(e).__name__}")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True, "llm": llm.describe(), "mock": s.use_mock}

    @app.post("/jobs", status_code=202)
    async def create_job(body: NewJob, request: Request):
        ip, t = (request.client.host if request.client else "?"), time.time()
        q = hits[ip]
        while q and t - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            raise HTTPException(429, "Too many requests; slow down.")
        q.append(t)
        if not body.url and not (body.pasted_text and body.pasted_text.strip()):
            raise HTTPException(422, "Provide a URL or pasted text.")
        formats = [f for f in body.formats if f in CONTENT_FORMATS]
        jid = repo.create_job(body.url, body.note, llm.describe())
        voice = VoiceProfile(**repo.get_voice())
        initial = {"job_id": jid, "input_url": body.url, "user_note": body.note, "pasted_text": body.pasted_text,
                   "formats": formats, "tone": body.tone, "depth": body.depth, "voice": voice,
                   "events": [], "candidates": [], "queries_log": []}
        task = asyncio.create_task(execute(jid, initial))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"id": jid, "status": "queued"}

    @app.get("/jobs")
    def list_jobs():
        return repo.list_jobs()

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        job = repo.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @app.get("/jobs/{job_id}/events")
    def get_events(job_id: str):
        if not repo.get_job(job_id):
            raise HTTPException(404, "Job not found")
        return repo.events(job_id)

    @app.patch("/jobs/{job_id}")
    def rename(job_id: str, body: Rename):
        if not repo.rename(job_id, body.name):
            raise HTTPException(404, "Job not found")
        return {"ok": True}

    @app.delete("/jobs/{job_id}")
    def delete(job_id: str):
        if not repo.delete(job_id):
            raise HTTPException(404, "Job not found")
        return {"ok": True}

    @app.get("/jobs/{job_id}/export/report.md", response_class=PlainTextResponse)
    def export_report(job_id: str):
        job = repo.get_job(job_id)
        if not job or not job["result"]:
            raise HTTPException(404, "No finished result for this job")
        return report_markdown(job)

    @app.get("/jobs/{job_id}/export/drafts.md", response_class=PlainTextResponse)
    def export_drafts(job_id: str):
        job = repo.get_job(job_id)
        if not job or not job["result"]:
            raise HTTPException(404, "No finished result for this job")
        return drafts_markdown(job)

    @app.get("/voice")
    def get_voice():
        return repo.get_voice()

    @app.put("/voice")
    def put_voice(v: VoiceProfile):
        repo.set_voice(v.model_dump())
        return {"ok": True}

    return app


def _dump(v):
    if v is None:
        return None
    if isinstance(v, list):
        return [_dump(x) for x in v]
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v


def _err_event(e: Exception):
    from packages.agent.schemas.models import JobEvent
    return JobEvent(stage="runner", event_type="error", message=f"Unhandled error: {type(e).__name__}")


def app_factory() -> FastAPI:  # uvicorn apps.api.main:app_factory --factory
    return create_app()
