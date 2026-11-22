from __future__ import annotations

from packages.config import Settings
from packages.providers.llm.base import LLM, OllamaLLM
from packages.providers.llm.mock import MockLLM


def build_llm(s: Settings) -> LLM:
    if s.use_mock or s.llm_provider == "mock":
        return MockLLM()
    if s.llm_provider == "ollama":
        return OllamaLLM(s.ollama_url, s.reasoning_model, s.fast_model, s.llm_timeout_s, s.llm_temperature)
    raise ValueError(f"unknown LLM_PROVIDER {s.llm_provider!r}")
