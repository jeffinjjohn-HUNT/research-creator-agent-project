# AI Research & Creator Agent

Paste a link or text about an AI tool, product or trend. The agent reads it, researches it across YouTube, Reddit, X and
news/web in parallel, checks the claims against sources, writes a **cited beginner learning report**, and drafts
**original** LinkedIn / X / Instagram / reel / carousel content in your voice. **Nothing is ever published for you**, and
the agent never logs in to accounts or bypasses paywalls — if a source is private it asks you to paste the text.

Built for the CodingCatalysts "AI Research & Creator Agent" intern project.

## How it works
`intake -> extract -> plan -> research (5 parallel branches) -> rank/dedupe -> claim check -> write report (section by section) -> drafts (one per format) -> quality checks -> save`

Orchestrated with **LangGraph** (typed state, parallel fan-out/join, early exit when a source is inaccessible).
See [docs/architecture.md](docs/architecture.md) and [docs/decisions/001-framework-langgraph.md](docs/decisions/001-framework-langgraph.md).

## Run it on Windows (easiest)
1. Install Python 3.12+ and [Ollama](https://ollama.com).
2. In a terminal: `ollama pull qwen2.5:3b-instruct`
3. Copy `.env.example` to `.env` and add a free [Tavily](https://tavily.com) key as `TAVILY_API_KEY=...`
4. Double-click **`run.bat`**. It creates a virtual environment, installs dependencies, and opens http://localhost:8000.

With no `.env`, `run.bat` starts **demo mode** (sample data, no model, no keys) so you can see the whole flow offline.

## Run it anywhere
```bash
pip install -r requirements.txt
cp .env.example .env                 # add your keys
uvicorn apps.api.main:app_factory --factory
```
Open http://localhost:8000 (web app) or http://localhost:8000/docs (API).

## Deploy (Render + Groq)
1. Push this repo to GitHub. Get a free key at [console.groq.com](https://console.groq.com) and a free [Tavily](https://tavily.com) key.
2. On [render.com](https://render.com): **New → Blueprint**, pick this repo. `render.yaml` sets everything up.
3. When asked, paste `GROQ_API_KEY` and `TAVILY_API_KEY`. Deploy, then open the `.onrender.com` URL.
Free-tier notes: the service sleeps after inactivity (first load takes ~30-60 s) and the SQLite history resets on restart.
Because keys are server-side, anyone with the URL can use your free quotas; a per-IP rate limit (10 jobs/min) is built in.

## Configuration (`.env`)
| Variable | Meaning | Default |
|---|---|---|
| `LLM_PROVIDER` | `ollama`, `groq` or `mock` | `ollama` |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_FAST_MODEL` | Hosted model for deployment | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` |
| `REASONING_MODEL` / `FAST_MODEL` | Ollama model names | `qwen2.5:3b-instruct` |
| `OLLAMA_URL` | Ollama server | `http://localhost:11434` |
| `LLM_TIMEOUT_S`, `LLM_CALL_BUDGET_S` | Per-request timeout / hard per-call budget | 300 |
| `OLLAMA_NUM_CTX`, `OLLAMA_NUM_PREDICT` | Context window / max output tokens | 8192 / 3072 |
| `TAVILY_API_KEY`, `BRAVE_API_KEY`, `YOUTUBE_API_KEY` | Search providers (all optional) | empty |
| `SEARCH_STAGE_BUDGET_S` | Hard time limit for the search stage | 45 |
| `MAX_EVIDENCE` | Evidence sources kept after ranking | 15 |
| `USE_MOCK` | `1` = offline demo with a deterministic mock model and mock search | 0 |

Missing search keys never break a run: coverage shrinks and the report says the evidence is thin instead of inventing sources.

## Model setup
Tested on a laptop with an RTX 3050 (4 GB VRAM) using `qwen2.5:3b-instruct` (~2 GB). Small models work best with short,
focused prompts, so the report is written one section at a time with only the most relevant evidence, and each social
format is generated in its own call. A 7B model needs more than 4 GB of VRAM to run fast.

## Safety and trust
- **SSRF protection** on every URL and every redirect hop (private/loopback/metadata addresses are refused).
- **Prompt-injection defence**: all fetched text is fenced as untrusted data; instruction-like text is flagged; model output is validated; no tool can be triggered by text.
- **No invented citations**: citations must resolve to stored evidence ids; unknown ids are dropped.
- **Claim checking**: a claim is only "supported" with 2+ independent domains; otherwise "partly supported". When the model fails to link a claim, an automatic text-overlap check is used and labelled as such.
- **Originality check**: drafts that reuse 8+ consecutive words from the source are flagged and retried once; names in drafts that no source mentions are flagged.
- Never auto-publishes. Never logs in or bypasses paywalls.

## API
`POST /jobs` · `GET /jobs` · `GET /jobs/{id}` · `GET /jobs/{id}/events` · `PATCH|DELETE /jobs/{id}` ·
`GET /jobs/{id}/export/report.md|drafts.md` · `GET|PUT /voice` · `GET /health`

Job status: `queued, running, needs_input, failed, completed, completed_with_warnings`.

## Tests and evaluation
```bash
pytest -q                              # 41 tests
USE_MOCK=1 python -m tests.evals.run   # 20 evaluation cases -> docs/eval_results.md
```
CI (GitHub Actions) runs the tests, the evaluation and the Docker build on every push. See [docs/evaluation.md](docs/evaluation.md).

## Known limitations
- Only one local model (`qwen2.5:3b-instruct`) has been tested live; a two-model benchmark is still to do.
- A 3B model writes basic text: some report sections (for example "Alternatives") can be shallow or circular. Always review before posting.
- Without a search key there is little evidence. X, YouTube and Reddit coverage depends on the search provider (their own APIs are paid or restricted); fallbacks are documented in the architecture doc.
- The 20 evaluation cases run in demo mode (mock model); hand-labelled accuracy on real runs is not yet measured.
- Frontend is a single-page web app (not Next.js); storage is SQLite (not Supabase). No auth, PDF export or deployed URL yet.
- Video transcripts are not fetched automatically; paste one if you have it.

## Roadmap
Hosted-model provider and deployment, two-model benchmark, PDF export, Supabase/pgvector, authentication, background queue,
human-review checkpoints.
