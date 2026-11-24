"""Model-provider interface. Business logic only ever sees `LLM.generate_json`."""
from __future__ import annotations

import asyncio
import json
import os
import re
from abc import ABC, abstractmethod
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


def extract_json(text: str) -> str:
    """Pull the first JSON object out of a model reply (handles ```json fences / chatter)."""
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        return fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("no JSON object found in model output")
    return text[start : end + 1]


class LLM(ABC):
    """Subclasses implement `_complete`; validation, repair retries and the time budget live here."""

    name: str = "llm"
    model: str = ""
    max_repairs: int = 2

    @abstractmethod
    async def _complete(self, system: str, prompt: str, *, fast: bool, schema: dict | None = None) -> str: ...

    async def generate_json(
        self, *, task: str, system: str, prompt: str, schema: type[T], fast: bool = False,
        budget_s: float | None = None,
    ) -> T:
        """Whole call (including repair attempts) must finish within the budget, or LLMError is raised
        so the caller's fallback runs instead of the job hanging."""
        budget = budget_s or float(os.getenv("LLM_CALL_BUDGET_S", "300"))
        try:
            return await asyncio.wait_for(
                self._generate_json(task=task, system=system, prompt=prompt, schema=schema, fast=fast), timeout=budget)
        except asyncio.TimeoutError as e:
            raise LLMError(f"{task}: model did not answer within {int(budget)}s") from e

    async def _generate_json(self, *, task, system, prompt, schema, fast):
        schema_dict = schema.model_json_schema()
        full_system = f"{system}\nReply with ONE JSON object matching this JSON Schema, no prose:\n{json.dumps(schema_dict)}"
        last_err = ""
        for _attempt in range(self.max_repairs + 1):
            user = prompt if not last_err else f"{prompt}\n\nYour previous reply was invalid: {last_err}\nReturn corrected JSON only."
            raw = await self._complete(full_system, user, fast=fast, schema=schema_dict)
            try:
                return schema.model_validate_json(extract_json(raw))
            except (LLMError, ValidationError, ValueError) as e:
                last_err = str(e)[:400]
        raise LLMError(f"{task}: model returned invalid JSON after {self.max_repairs + 1} attempts: {last_err}")

    def describe(self) -> dict:
        return {"provider": self.name, "model": self.model}


class OllamaLLM(LLM):
    name = "ollama"

    def __init__(self, url: str, reasoning_model: str, fast_model: str, timeout_s: float, temperature: float):
        self.url, self.timeout_s, self.temperature = url.rstrip("/"), timeout_s, temperature
        self.reasoning_model, self.fast_model = reasoning_model, fast_model
        self.model = reasoning_model

    async def _complete(self, system: str, prompt: str, *, fast: bool, schema: dict | None = None) -> str:
        model = self.fast_model if fast else self.reasoning_model
        payload = {
            "model": model,
            "stream": False,
            # Structured output: Ollama constrains decoding to the JSON schema, so the model cannot ramble or emit
            # broken JSON. Falls back to plain JSON mode if this Ollama version rejects the schema.
            "format": schema if schema else "json",
            "keep_alive": "20m",  # keep the model loaded between pipeline steps
            "options": {
                "temperature": self.temperature,
                # Ollama's default context is 4096 tokens and silently truncates longer prompts.
                "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
                "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "3072")),  # cap output length
            },
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                r = await client.post(f"{self.url}/api/chat", json=payload)
                if r.status_code == 400 and schema:
                    payload["format"] = "json"
                    r = await client.post(f"{self.url}/api/chat", json=payload)
                r.raise_for_status()
                return r.json()["message"]["content"]
        except (httpx.HTTPError, KeyError) as e:
            raise LLMError(f"ollama request failed: {type(e).__name__}") from e

    def describe(self) -> dict:
        return {"provider": self.name, "reasoning_model": self.reasoning_model, "fast_model": self.fast_model,
                "temperature": self.temperature}


class GroqLLM(LLM):
    """Groq's OpenAI-compatible chat API (free tier available). Works with any OpenAI-compatible server via GROQ_URL."""
    name = "groq"

    def __init__(self, api_key: str, model: str, fast_model: str, timeout_s: float, temperature: float,
                 url: str = "https://api.groq.com/openai/v1"):
        if not api_key:
            raise ValueError("GROQ_API_KEY is empty. Add it to .env or the host's environment variables.")
        self.api_key, self.url, self.timeout_s, self.temperature = api_key, url.rstrip("/"), timeout_s, temperature
        self.reasoning_model, self.fast_model = model, fast_model
        self.model = model

    async def _complete(self, system: str, prompt: str, *, fast: bool, schema: dict | None = None) -> str:
        model = self.fast_model if fast else self.reasoning_model
        payload = {
            "model": model,
            "temperature": self.temperature,
            "max_tokens": int(os.getenv("GROQ_MAX_TOKENS", "4096")),
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        if "gpt-oss" in model:  # reasoning models: keep thinking short so tokens go to the JSON answer
            payload["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "low")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                for attempt in range(6):  # free tiers rate-limit: wait and retry instead of failing the job
                    r = await client.post(f"{self.url}/chat/completions", json=payload, headers=headers)
                    if r.status_code == 429 and attempt < 5:
                        try:
                            wait = float(r.headers.get("retry-after", "") or 2 * (attempt + 1))
                        except ValueError:
                            wait = 2 * (attempt + 1)
                        await asyncio.sleep(min(wait, float(os.getenv("GROQ_MAX_WAIT_S", "45"))))
                        continue
                    if r.status_code >= 400:  # say WHY (rate limit, bad key, bad model...) so it can be fixed
                        raise LLMError(f"groq HTTP {r.status_code}: {r.text[:200]}")
                    return r.json()["choices"][0]["message"]["content"]
        except LLMError:
            raise
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"groq request failed: {type(e).__name__}") from e
        raise LLMError("groq request failed: rate limited")  # pragma: no cover

    def describe(self) -> dict:
        return {"provider": self.name, "reasoning_model": self.reasoning_model, "fast_model": self.fast_model,
                "temperature": self.temperature}
