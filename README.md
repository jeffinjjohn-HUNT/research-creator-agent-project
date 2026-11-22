# AI Research & Creator Agent

Paste a link (or text) about an AI tool/trend -> the agent extracts what it can, researches across YouTube, Reddit, X and
news/web in parallel, checks the claims, writes a cited beginner learning report, and drafts original content in your
voice. Nothing is auto-published. See `docs/architecture.md`.

## Quick start (offline demo, no keys, no model)
```bash
pip install -r requirements.txt
USE_MOCK=1 python -m pytest -q
USE_MOCK=1 uvicorn apps.api.main:app_factory --factory --reload
curl -s localhost:8000/jobs -H 'content-type: application/json' \
  -d '{"pasted_text":"ExampleTool is a new AI tool that runs locally."}'
curl -s localhost:8000/jobs/<id>/events      # real per-stage progress
curl -s localhost:8000/jobs/<id>/export/report.md
```

## Real run
1. Install [Ollama](https://ollama.com), then `ollama pull qwen2.5:7b-instruct` and `ollama pull qwen2.5:3b-instruct` (swap models via env).
2. `cp .env.example .env` and add whichever keys you have (Tavily/Brave, YouTube). Missing keys just shrink coverage.
3. `uvicorn apps.api.main:app_factory --factory`

## Easiest way: web page
Start the server, then open http://localhost:8000 and use the form. (The API docs are at /docs.)

## API
`POST /jobs` · `GET /jobs` · `GET /jobs/{id}` · `GET /jobs/{id}/events` · `PATCH|DELETE /jobs/{id}` ·
`GET /jobs/{id}/export/report.md|drafts.md` · `GET|PUT /voice` · `GET /health`

Job status: `queued, running, needs_input, failed, completed, completed_with_warnings`.

## Tests & eval
`pytest -q` (35 tests) and `USE_MOCK=1 python -m tests.evals.run` (20 cases).

## Status
Backend, agent graph, persistence, Markdown export, tests, eval harness, Dockerfile and CI are done.
Not yet built: Next.js UI, PDF export, Supabase, auth, deployment, demo video, live-model benchmark.
