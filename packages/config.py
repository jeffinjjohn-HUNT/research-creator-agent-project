"""Central configuration. All secrets come from environment variables, never from code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader (no extra dependency). Real environment variables win over the file."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # LLM (model is configuration, never hard-coded in business logic)
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "ollama"))
    reasoning_model: str = field(default_factory=lambda: os.getenv("REASONING_MODEL", "qwen2.5:7b-instruct"))
    fast_model: str = field(default_factory=lambda: os.getenv("FAST_MODEL", "qwen2.5:3b-instruct"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "120")))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.2")))

    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    groq_fast_model: str = field(default_factory=lambda: os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant"))
    groq_url: str = field(default_factory=lambda: os.getenv("GROQ_URL", "https://api.groq.com/openai/v1"))

    # Search providers (all optional; fallbacks are documented in docs/architecture.md)
    tavily_api_key: str = field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    brave_api_key: str = field(default_factory=lambda: os.getenv("BRAVE_API_KEY", ""))
    youtube_api_key: str = field(default_factory=lambda: os.getenv("YOUTUBE_API_KEY", ""))

    # Budgets / resilience
    search_timeout_s: float = field(default_factory=lambda: float(os.getenv("SEARCH_TIMEOUT_S", "15")))
    search_retries: int = field(default_factory=lambda: int(os.getenv("SEARCH_RETRIES", "2")))
    max_queries_per_platform: int = field(default_factory=lambda: int(os.getenv("MAX_QUERIES_PER_PLATFORM", "3")))
    max_results_per_query: int = field(default_factory=lambda: int(os.getenv("MAX_RESULTS_PER_QUERY", "5")))
    max_evidence: int = field(default_factory=lambda: int(os.getenv("MAX_EVIDENCE", "15")))

    # Storage
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/app.db"))

    # Offline demo / tests: deterministic mock LLM + mock search, no network
    use_mock: bool = field(default_factory=lambda: _bool("USE_MOCK", False))


def get_settings() -> Settings:
    return Settings()
