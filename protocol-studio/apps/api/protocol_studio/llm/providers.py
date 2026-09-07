"""Provider adapters.

Each adapter turns a ``Request`` (system + user text) into a ``Result`` (text +
token counts). Adding a vendor = one small class + one ``PROVIDERS`` entry; the
gateway, policy, admin UI and tests need no change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    default_model: str
    models: tuple[str, ...]
    default_base_url: str
    env_key: str  # environment variable consulted when no key is stored in the DB
    docs_url: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        default_model="gpt-6-astra",
        models=("gpt-6-astra",),
        default_base_url="https://api.openai.com/v1",
        env_key="OPENAI_API_KEY",
        docs_url="https://developers.openai.com/api/docs/models/gpt-6-astra",
    ),
    # Wire-compatible vendors land here as further specs + adapters, e.g.
    # "grok": ProviderSpec("grok", "xAI Grok", "grok-4", ("grok-4",), "https://api.x.ai/v1", "XAI_API_KEY"),
}


@dataclass
class Request:
    system: str
    user: str
    model: str
    max_output_tokens: int = 1200


@dataclass
class Result:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class ProviderError(RuntimeError):
    """Upstream failure (network, auth, 4xx/5xx). Message is safe to show to an admin."""


class Provider(Protocol):
    def complete(self, req: Request) -> Result: ...

    def ping(self) -> str:
        """Cheap connectivity/auth check; returns a human-readable status line."""
        ...


class OpenAIResponses:
    """OpenAI Responses API (``POST /responses``)."""

    def __init__(self, api_key: str, base_url: str = "", timeout: float = 60.0) -> None:
        self._key = api_key
        self._base = (base_url or PROVIDERS["openai"].default_base_url).rstrip("/")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def complete(self, req: Request) -> Result:
        body = {
            "model": req.model,
            "instructions": req.system,
            "input": req.user,
            "max_output_tokens": req.max_output_tokens,
            "store": False,
        }
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{self._base}/responses", json=body, headers=self._headers(), timeout=self._timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"openai: network error: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise ProviderError(f"openai: HTTP {r.status_code}: {_error_message(r)}")
        data = r.json()
        usage = data.get("usage") or {}
        return Result(
            text=_output_text(data),
            model=str(data.get("model") or req.model),
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            raw=data,
        )

    def ping(self) -> str:
        try:
            r = httpx.get(f"{self._base}/models", headers=self._headers(), timeout=15.0)
        except httpx.HTTPError as e:
            raise ProviderError(f"openai: network error: {e.__class__.__name__}") from e
        if r.status_code >= 400:
            raise ProviderError(f"openai: HTTP {r.status_code}: {_error_message(r)}")
        ids = [m.get("id", "") for m in r.json().get("data", [])]
        wanted = [m for m in PROVIDERS["openai"].models if m in ids]
        return f"ok — {len(ids)} models visible; {', '.join(wanted) or 'none of the configured models'} available"


def _error_message(r: httpx.Response) -> str:
    try:
        err = r.json().get("error") or {}
        return str(err.get("message") or r.text[:200])
    except ValueError:
        return r.text[:200]


def _output_text(data: dict[str, Any]) -> str:
    """Responses API: ``output`` is a list of items; message items carry ``content`` parts with ``text``."""
    if isinstance(data.get("output_text"), str):
        return str(data["output_text"])
    parts: list[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "".join(parts).strip()


def make_provider(spec: ProviderSpec, api_key: str, base_url: str = "") -> Provider:
    if spec.id == "openai":
        return OpenAIResponses(api_key, base_url)
    raise ProviderError(f"no adapter for provider {spec.id}")
