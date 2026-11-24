from __future__ import annotations

from packages.config import Settings
from packages.providers.llm.base import LLM, GroqLLM, OllamaLLM
from packages.providers.llm.mock import MockLLM


def build_llm(s: Settings) -> LLM:
    if s.use_mock or s.llm_provider == "mock":
        return MockLLM()
    if s.llm_provider == "ollama":
        return OllamaLLM(s.ollama_url, s.reasoning_model, s.fast_model, s.llm_timeout_s, s.llm_temperature)
    if s.llm_provider == "groq":
        return GroqLLM(s.groq_api_key, s.groq_model, s.groq_fast_model, s.llm_timeout_s, s.llm_temperature, s.groq_url)
    raise ValueError(f"unknown LLM_PROVIDER {s.llm_provider!r}")
