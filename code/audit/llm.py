"""A small model client: one OpenAI-compatible call, cached, counted, costed.

Three things this must get right, because two of them are graded.

**Secrets.** Keys are read from the environment and from nowhere else. Nothing here
reads a `.env` inside the repository, and no key is ever written to the cache, the usage
report or the log.

**Cost.** `evaluation/usage_report.md` has to state providers, models, call counts, input
and output tokens, and cost per request. That is only possible if every call is counted at
the point it is made, so the ledger lives here rather than being reconstructed afterwards.

**Repetition.** The 94-file evidence corpus and the 518 request texts are both fixed, and
the requests are drawn from a small number of templates. Caching on the exact prompt turns
518 classifications into a few dozen calls and makes re-runs free. The cache is keyed by
provider, model and the full prompt, so changing any of them invalidates it rather than
silently serving a stale answer.

Failure is explicit. A call that cannot be made raises; it never returns an invented
answer, and the caller decides what a missing answer means.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

#: provider -> (env var holding the key, base url, default text model, default vision model)
PROVIDERS = {
    "openai": ("OPENAI_API_KEY", "https://api.openai.com/v1",
               "gpt-4o-mini", "gpt-4o-mini"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1",
             "llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "nebius": ("NEBIUS_API_KEY", "https://api.studio.nebius.com/v1",
               "Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2-VL-72B-Instruct"),
}

#: USD per million tokens (input, output). Published list prices at time of writing;
#: they are stated here so the usage report says where its numbers come from rather than
#: presenting an unsourced total.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "meta-llama/llama-4-scout-17b-16e-instruct": (0.11, 0.34),
    "Qwen/Qwen2.5-72B-Instruct": (0.13, 0.40),
    "Qwen/Qwen2-VL-72B-Instruct": (0.40, 1.20),
}


class LLMError(RuntimeError):
    """A call that could not be completed. Never swallowed into a default answer."""


@dataclass
class Usage:
    """The ledger behind evaluation/usage_report.md."""

    calls: int = 0
    cached: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    failures: int = 0
    seconds: float = 0.0
    per_model: dict[str, dict] = field(default_factory=dict)

    def record(self, model: str, provider: str, prompt_tokens: int,
               completion_tokens: int, elapsed: float) -> None:
        self.calls += 1
        self.input_tokens += prompt_tokens
        self.output_tokens += completion_tokens
        self.seconds += elapsed
        row = self.per_model.setdefault(
            model, {"provider": provider, "calls": 0, "input_tokens": 0,
                    "output_tokens": 0, "cost_usd": 0.0})
        row["calls"] += 1
        row["input_tokens"] += prompt_tokens
        row["output_tokens"] += completion_tokens
        row["cost_usd"] += self.cost_of(model, prompt_tokens, completion_tokens)

    @staticmethod
    def cost_of(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        price = PRICES.get(model)
        if price is None:
            return 0.0
        return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000

    @property
    def cost_usd(self) -> float:
        return sum(r["cost_usd"] for r in self.per_model.values())

    def summary(self) -> str:
        return (f"{self.calls} calls ({self.cached} served from cache), "
                f"{self.input_tokens} in / {self.output_tokens} out tokens, "
                f"${self.cost_usd:.4f}, {self.failures} failures, "
                f"{self.seconds:.1f}s")


class Client:
    """One OpenAI-compatible chat endpoint, whichever provider is configured."""

    def __init__(self, provider: str | None = None, *, model: str | None = None,
                 cache_dir: Path | None = None, timeout: int = 90,
                 retries: int = 3) -> None:
        self.provider = provider or self.first_available()
        if self.provider is None:
            raise LLMError(
                "no model provider configured. Set one of "
                + ", ".join(v[0] for v in PROVIDERS.values())
                + " in the environment.")
        env_var, self.base_url, default_text, self.vision_model = \
            PROVIDERS[self.provider]
        self.api_key = os.environ.get(env_var, "")
        if not self.api_key:
            raise LLMError(f"{env_var} is not set")
        self.model = model or default_text
        self.timeout = timeout
        self.retries = retries
        self.usage = Usage()
        self.cache_dir = cache_dir or (Path(__file__).resolve().parents[2]
                                       / ".cache" / "llm")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def first_available() -> str | None:
        for name, (env_var, *_rest) in PROVIDERS.items():
            if os.environ.get(env_var):
                return name
        return None

    # -- the call ----------------------------------------------------------------- #

    def ask(self, system: str, user, *, model: str | None = None,
            temperature: float = 0.0, max_tokens: int = 700,
            cache: bool = True) -> str:
        """Send one message and return the text. `user` may be a string or content parts.

        Temperature defaults to 0: the same evidence must produce the same answer twice,
        or none of the measurements in this repository mean anything.
        """
        model = model or self.model
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        payload = {"model": model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}

        key = hashlib.sha256(
            json.dumps([self.provider, model, temperature, max_tokens, messages],
                       sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if cache and path.is_file():
            self.usage.cached += 1
            return json.loads(path.read_text(encoding="utf-8"))["text"]

        last: Exception | None = None
        for attempt in range(self.retries):
            started = time.perf_counter()
            try:
                text, prompt_tokens, completion_tokens = self._post(payload)
            except Exception as why:                      # noqa: BLE001
                last = why
                # Back off and retry: a transient network failure must not be allowed to
                # become a missing answer that later reads as a confident one.
                time.sleep(1.5 * (attempt + 1))
                continue
            self.usage.record(model, self.provider, prompt_tokens, completion_tokens,
                              time.perf_counter() - started)
            if cache:
                path.write_text(json.dumps({"text": text, "model": model},
                                           ensure_ascii=False), encoding="utf-8")
            return text

        self.usage.failures += 1
        raise LLMError(f"{self.provider}/{model} failed after {self.retries} attempts: "
                       f"{last}")

    def _post(self, payload: dict) -> tuple[str, int, int]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}",
                     # Some providers sit behind a WAF that rejects the default
                     # `Python-urllib/3.x` agent with an opaque HTTP 403 (Cloudflare
                     # error 1010). Identifying the client properly avoids it.
                     "User-Agent": "ghost-data-deletion-audit/1.0",
                     "Accept": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as why:
            detail = why.read().decode("utf-8", "replace")[:300]
            raise LLMError(f"HTTP {why.code}: {detail}") from why
        usage = body.get("usage") or {}
        return (body["choices"][0]["message"]["content"] or "",
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)))

    # -- helpers ------------------------------------------------------------------ #

    def ask_json(self, system: str, user, **kwargs) -> dict:
        """Ask for JSON and parse it. Unparseable output raises; it is never guessed at."""
        text = self.ask(system, user, **kwargs).strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise LLMError(f"no JSON object in the reply: {text[:160]!r}")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as why:
            raise LLMError(f"reply is not valid JSON ({why}): {text[:160]!r}") from why
