"""Auditable, stateless JSON providers using only the Python standard library.

``Provider.complete(stage, prompt, images=(), schema=None)`` returns a JSON object.
Each HTTP attempt is reserved and journaled separately; retries are opt-in (0 or 1).
``usage.jsonl`` has start/finish events and exact provider-reported usage, while
``raw/`` holds response artifacts. Cache/replay/exchange usage is never billed as
live usage. ``summary()`` reports unknowns explicitly, not as zero tokens/cost.

Pricing keys are ``input``, ``cached`` and ``output`` in USD per million tokens.
The optional monetary guard bounds an *estimate*, not an invoice: it reserves
UTF-8 text bytes / 3 + 64 input tokens + 4096 per image, plus the output limit.
Use max_calls / max_reserved_output_tokens for deterministic request bounds.
Reasoning tokens are an output subset and are never added to output a second time.

Chat Completions reference checked 2026-09-06:
https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib import error, parse, request
import uuid


class ProviderError(RuntimeError):
    """A provider failed; details and any available usage are in the journal."""


class InvalidResponse(ProviderError):
    """The response was not a finite JSON object or a valid completion."""


class BudgetExceeded(ProviderError):
    """A new attempt would exceed an explicitly configured limit."""


class PendingResponse(ProviderError):
    """An external worker must fill response_path before this stage can resume."""

    def __init__(self, request_path: Path, response_path: Path):
        self.request_path = request_path
        self.response_path = response_path
        super().__init__(f"External response pending: {request_path}")


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidResponse("Non-finite numbers are not valid response data")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidResponse("Duplicate JSON object keys are not accepted")
        result[key] = value
    return result


def parse_json_object(text: str) -> dict[str, Any]:
    """Strict JSON only: no Markdown extraction, code evaluation, NaN or infinity."""
    try:
        value = json.loads(text, object_pairs_hook=_pairs)
        _finite(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidResponse("Response is not valid finite JSON") from exc
    if not isinstance(value, dict):
        raise InvalidResponse("Response JSON must be an object")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(_json(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonnegative(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")


@dataclass(frozen=True)
class ModelConfig:
    name: str
    base_url: str
    api_key_env: str | None = None
    max_output_tokens: int = 2500
    temperature: float | None = None
    json_mode: bool = False
    timeout_s: float = 120
    pricing: Mapping[str, float] | None = None
    token_limit_param: str = "max_completion_tokens"
    reasoning_effort: str | None = None
    wire_api: str = "chat"
    image_detail: str | None = None

    def __post_init__(self) -> None:
        if self.wire_api not in {"chat", "responses"}: raise ValueError("Unsupported wire_api")
        if self.image_detail not in {None,"auto","low","high"}: raise ValueError("Unsupported image_detail")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("A model name is required")
        url = parse.urlsplit(self.base_url)
        if url.scheme not in {"http", "https"} or not url.netloc:
            raise ValueError("base_url must be an http(s) URL")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("base_url must not contain credentials, a query, or a fragment")
        if self.api_key_env is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env):
            raise ValueError("api_key_env must be an environment variable name")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer")
        _nonnegative(self.timeout_s, "timeout_s")
        if self.timeout_s == 0:
            raise ValueError("timeout_s must be positive")
        if self.temperature is not None:
            _nonnegative(self.temperature, "temperature")
        if self.token_limit_param not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("token_limit_param must be max_tokens or max_completion_tokens")
        if self.reasoning_effort not in {None, "none", "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("Unsupported reasoning_effort")
        if self.pricing is not None:
            if not {"input", "output"}.issubset(self.pricing) or set(self.pricing) - {"input", "cached", "output"}:
                raise ValueError("pricing requires input/output and optional cached USD per million")
            for key, value in self.pricing.items():
                _nonnegative(value, f"pricing.{key}")

    @property
    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        suffix = "/responses" if self.wire_api == "responses" else "/chat/completions"
        return base if base.endswith(suffix) else base + suffix


def normalize_usage(usage: Any) -> dict[str, int | None]:
    """Keep absent/malformed counters unknown. Cached/reasoning are subsets."""
    result = dict.fromkeys(("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"))
    if not isinstance(usage, dict):
        return result
    def count(value: Any) -> int | None:
        return value if type(value) is int and value >= 0 else None
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    output_details = usage.get("completion_tokens_details") or usage.get("output_tokens_details") or {}
    result["input_tokens"] = count(usage.get("prompt_tokens", usage.get("input_tokens")))
    result["output_tokens"] = count(usage.get("completion_tokens", usage.get("output_tokens")))
    result["total_tokens"] = count(usage.get("total_tokens"))
    if isinstance(prompt_details, dict):
        result["cached_input_tokens"] = count(prompt_details.get("cached_tokens"))
    if isinstance(output_details, dict):
        result["reasoning_tokens"] = count(output_details.get("reasoning_tokens"))
    return result


def estimate_cost(usage: Any, pricing: Mapping[str, float] | None) -> float | None:
    """Cost from reported counters and user prices; None if needed data is absent."""
    if pricing is None:
        return None
    counts = normalize_usage(usage)
    inp, out, cached = (counts[k] for k in ("input_tokens", "output_tokens", "cached_input_tokens"))
    if inp is None or out is None:
        return None
    cached_rate = pricing.get("cached", pricing["input"])
    if cached is None:
        if cached_rate != pricing["input"]:
            return None
        cached = 0  # Equal rates make the absent subset immaterial to cost only.
    if cached > inp:
        return None
    return ((inp - cached) * pricing["input"] + cached * cached_rate + out * pricing["output"]) / 1_000_000


def _response_data(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("object") == "response" or "output" in response:
        if response.get("status") != "completed": raise InvalidResponse("Responses request did not complete")
        parts=[]
        for item in response.get("output",[]):
            if item.get("type")=="reasoning": continue
            if item.get("type")!="message": raise InvalidResponse("Unexpected Responses output type")
            for part in item.get("content",[]):
                if part.get("type")!="output_text": raise InvalidResponse("Expected Responses text only")
                parts.append(part["text"])
        return parse_json_object("".join(parts))
    try:
        choice = response["choices"][0]
        message = choice["message"]
        if choice.get("finish_reason") == "length":
            raise InvalidResponse("Completion hit its output limit")
        if message.get("refusal") or message.get("tool_calls") or message.get("function_call"):
            raise InvalidResponse("Expected JSON text, received refusal or tool call")
        content = message["content"]
        if isinstance(content, list):
            if not all(isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str) for part in content):
                raise InvalidResponse("Expected text content only")
            content = "".join(part["text"] for part in content)
        if not isinstance(content, str):
            raise InvalidResponse("Completion has no text content")
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise InvalidResponse("Response does not contain a chat completion") from exc
    return parse_json_object(content)


def _image_inputs(images: Sequence[Path]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    metadata, contents = [], []
    for item in images:
        path = Path(item)
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("Images must be PNG, JPEG, WEBP, or GIF files")
        metadata.append({"sha256": hashlib.sha256(data).hexdigest(), "mime_type": mime, "size_bytes": len(data)})
        contents.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")}})
    return metadata, contents


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Journal:
    def __init__(self, artifact_dir: Path | str, mode: str):
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.usage_path = self.artifact_dir / "usage.jsonl"
        self.run_id = uuid.uuid4().hex
        self.provider_mode = mode
        self.records: list[dict[str, Any]] = []
        if self.usage_path.exists():
            # Fail closed on a damaged journal rather than forgetting reservations.
            self.records = [parse_json_object(line) for line in self.usage_path.read_text().splitlines() if line.strip()]

    def _record(self, record: dict[str, Any]) -> None:
        record = {"timestamp": _now(), "run_id": self.run_id, "provider_mode": self.provider_mode, **record}
        with self.usage_path.open("a", encoding="utf-8") as handle:
            handle.write(_json(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(record)

    def summary(self) -> dict[str, Any]:
        finished = [r for r in self.records if r["event"] == "attempt_finished"]
        started = [r for r in self.records if r["event"] == "attempt_started"]
        known_cost = sum(r["estimated_cost_usd"] for r in finished if r.get("estimated_cost_usd") is not None)
        external_unknown = len({r.get('raw_artifact',r.get('cache_key')) for r in self.records if r['event']=='external_exchange'})
        unknown_cost = sum(r.get("estimated_cost_usd") is None for r in finished) + len(started) - len(finished) + external_unknown
        totals = {}
        missing = {}
        for key in normalize_usage(None):
            values = [normalize_usage(r.get("reported_usage"))[key] for r in finished]
            totals[key] = sum(v for v in values if v is not None)
            missing[key] = sum(v is None for v in values) + len(started) - len(finished) + external_unknown
        return {
            "provider_mode": self.provider_mode, "run_id": self.run_id,
            "accounting_scope": "cumulative_artifact_directory", "run_id_scope": "current_process_instance",
            "live_attempts": len(started), "completed_attempts": len(finished),
            "cache_hits": sum(r["event"] == "cache_hit" for r in self.records),
            "replay_calls": sum(r["event"] == "replay" for r in self.records),
            "exchange_calls": external_unknown,
            "supplied_response_cache_hits": sum(r["event"] == "supplied_response_cache" for r in self.records),
            "reported_known_token_subtotals": totals, "unknown_token_attempt_counts": missing,
            "estimated_known_cost_usd": known_cost,
            "estimated_cost_usd_total": None if unknown_cost else known_cost,
            "unknown_cost_attempts": unknown_cost,
            "reserved_output_tokens": getattr(self, "reserved_output_tokens", 0),
            "estimated_reserved_cost_usd": getattr(self, "estimated_reserved_cost_usd", None),
        }


class Provider(_Journal):
    """Serial-use HTTP provider. Every complete call contains one fresh user message.

    ModelConfig stores only a credential environment-variable *name*. The value is
    loaded immediately before a live request and is never put into request logs.
    Redirects are refused to avoid forwarding credentials to another endpoint.
    """
    def __init__(self, config: ModelConfig, artifact_dir: Path | str, *, cache_dir: Path | str | None = None,
                 max_calls: int | None = 100, max_estimated_cost_usd: float | None = None,
                 max_reserved_output_tokens: int | None = None, max_retries: int = 0):
        super().__init__(artifact_dir, "live_api")
        self.config = config
        self.cache_dir = Path(cache_dir) if cache_dir is not None else self.artifact_dir / "cache"
        self.max_calls = max_calls
        self.max_estimated_cost_usd = max_estimated_cost_usd
        self.max_reserved_output_tokens = max_reserved_output_tokens
        if max_retries not in (0, 1) or isinstance(max_retries, bool):
            raise ValueError("max_retries must be 0 (default) or 1")
        self.max_retries = max_retries
        for name, value in (("max_calls", max_calls), ("max_reserved_output_tokens", max_reserved_output_tokens)):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a nonnegative integer")
        if max_estimated_cost_usd is not None:
            _nonnegative(max_estimated_cost_usd, "max_estimated_cost_usd")
            if config.pricing is None:
                raise ValueError("An estimated dollar budget requires explicit pricing")
        if max_calls is None and max_estimated_cost_usd is None and max_reserved_output_tokens is None:
            raise ValueError("At least one request, output-token, or estimated-cost limit is required")
        started = [r for r in self.records if r['event']=='attempt_started']
        self.live_attempts = len(started)
        if any(type(r.get('reserved_output_tokens')) is not int or r['reserved_output_tokens']<0 for r in started):
            raise ProviderError('Prior output reservations are unreadable; cannot safely resume this journal')
        self.reserved_output_tokens = sum(r['reserved_output_tokens'] for r in started)
        prior_costs = [r.get('estimated_reserved_cost_usd') for r in started]
        if max_estimated_cost_usd is not None and any(v is None for v in prior_costs):
            raise ProviderError('Prior cost reservations are unknown; cannot enforce a new cost limit on this journal')
        self.estimated_reserved_cost_usd = sum(v for v in prior_costs if v is not None) if config.pricing else None
        self._opener = request.build_opener(_NoRedirect())

    def _reserve(self, prompt: str, image_count: int) -> float | None:
        output = self.config.max_output_tokens
        estimate = None
        if self.config.pricing is not None:
            inp = math.ceil(len(prompt.encode("utf-8")) / 3) + 64 + 4096 * image_count
            estimate = (inp * max(self.config.pricing["input"], self.config.pricing.get("cached", 0)) + output * self.config.pricing["output"]) / 1_000_000
        if self.max_calls is not None and self.live_attempts >= self.max_calls:
            raise BudgetExceeded("Maximum live HTTP attempts reached")
        if self.max_reserved_output_tokens is not None and self.reserved_output_tokens + output > self.max_reserved_output_tokens:
            raise BudgetExceeded("Output-token reservation budget would be exceeded")
        if self.max_estimated_cost_usd is not None and self.estimated_reserved_cost_usd + estimate > self.max_estimated_cost_usd:
            raise BudgetExceeded("Estimated-cost reservation budget would be exceeded")
        self.live_attempts += 1
        self.reserved_output_tokens += output
        if estimate is not None:
            self.estimated_reserved_cost_usd += estimate
        return estimate

    def complete(self, stage: str, prompt: str, images: Sequence[Path] = (), schema: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(stage, str) or not isinstance(prompt, str):
            raise ValueError("stage and prompt must be strings")
        metadata, image_content = _image_inputs(images)
        if schema is not None:
            parse_json_object(_json(schema))
        effective_prompt = prompt + "\n\nReturn only a valid JSON object, with finite numbers; do not include Markdown fences."
        if schema is not None:
            effective_prompt += "\nRequired JSON schema:\n" + _json(schema)
        settings = {"model": self.config.name, self.config.token_limit_param: self.config.max_output_tokens}
        if self.config.reasoning_effort is not None:
            settings["reasoning_effort"] = self.config.reasoning_effort
        if self.config.temperature is not None:
            settings["temperature"] = self.config.temperature
        if self.config.json_mode:
            settings["response_format"] = {"type": "json_object"}
        if self.config.wire_api == "responses":
            settings.pop(self.config.token_limit_param)
            settings["max_output_tokens"] = self.config.max_output_tokens
            settings["store"] = False
            if "reasoning_effort" in settings: settings["reasoning"]={"effort":settings.pop("reasoning_effort")}
            if "response_format" in settings: settings["text"]={"format":settings.pop("response_format")}
        settings_identity={**settings,"image_detail":self.config.image_detail}
        identity = {"cache_version": 1, "endpoint": self.config.endpoint, "settings": settings_identity,
                    "prompt": effective_prompt, "images": metadata, "schema": schema}
        key = _digest(identity)
        cache_path = self.cache_dir / (key + ".json")
        common = {"stage": stage, "model": self.config.name, "endpoint": self.config.endpoint,
                  "api_key_env": self.config.api_key_env, "cache_key": key,
                  "prompt_sha256": hashlib.sha256(effective_prompt.encode()).hexdigest(), "images": metadata}
        if cache_path.exists():
            cached = parse_json_object(cache_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") != key or cached.get("provider_mode") != "live_api":
                raise InvalidResponse("Cache identity or provenance does not match")
            result = _response_data(cached["response"])
            self._record({**common, "event": "cache_hit", "reported_usage": None,
                          "source_reported_usage": cached["response"].get("usage"),
                          "estimated_cost_usd": 0.0, "billed_this_run_usd": 0.0,
                          "live_request": False, "raw_artifact": str(cache_path)})
            return result
        secret = None
        if self.config.api_key_env:
            secret = os.environ.get(self.config.api_key_env)
            if not secret:
                raise ProviderError(f"Required credential environment variable is unset: {self.config.api_key_env}")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if secret:
            headers["Authorization"] = "Bearer " + secret
        body = {**settings, "messages": [{"role": "user", "content": [{"type": "text", "text": effective_prompt}, *image_content]}], "stream": False}
        if self.config.image_detail:
            for part in image_content: part["image_url"]["detail"]=self.config.image_detail
        if self.config.wire_api == "responses":
            content=[{"type":"input_text","text":effective_prompt}]
            for part in image_content:
                item={"type":"input_image","image_url":part["image_url"]["url"]}
                if self.config.image_detail:item["detail"]=self.config.image_detail
                content.append(item)
            body={**settings,"input":[{"role":"user","content":content}],"stream":False}
        encoded = _json(body).encode("utf-8")
        for attempt in range(1, self.max_retries + 2):
            reservation = self._reserve(effective_prompt, len(images))
            attempt_id = uuid.uuid4().hex
            attempt_common = {**common, "attempt_id": attempt_id, "attempt_number": attempt,
                              "live_request": True, "reserved_output_tokens": self.config.max_output_tokens,
                              "estimated_reserved_cost_usd": reservation}
            self._record({**attempt_common, "event": "attempt_started", "reported_usage": None,
                          "billed_this_run_usd": None, "estimated_cost_usd": None})
            started = time.monotonic()
            status, raw_text, response, result, failure, transient = None, None, None, None, None, False
            try:
                req = request.Request(self.config.endpoint, data=encoded, headers=headers, method="POST")
                try:
                    with self._opener.open(req, timeout=self.config.timeout_s) as handle:
                        status = handle.status
                        raw_bytes = handle.read(16 * 1024 * 1024 + 1)
                except error.HTTPError as exc:
                    status = exc.code
                    raw_bytes = exc.read(16 * 1024 * 1024 + 1)
                if len(raw_bytes) > 16 * 1024 * 1024:
                    raise InvalidResponse("HTTP response exceeds 16 MiB limit")
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                try:
                    response = parse_json_object(raw_text)
                except InvalidResponse:
                    if status is not None and not 200 <= status < 300:
                        transient = status in {408, 429, 500, 502, 503, 504}
                        raise ProviderError(f"HTTP {status}; response was not valid JSON")
                    raise
                if status is not None and not 200 <= status < 300:
                    transient = status in {408, 429, 500, 502, 503, 504}
                    raise ProviderError(f"HTTP {status}")
                result = _response_data(response)
            except (error.URLError, TimeoutError, ConnectionError) as exc:
                transient = True
                failure = ProviderError(f"Transport failure: {type(exc).__name__}")
            except ProviderError as exc:
                failure = exc
            except BaseException as exc:
                failure = exc
            finally:
                # Never journal headers, request bodies, data URLs, or credential values.
                def redact(text: str) -> str:
                    if secret:
                        text = text.replace(secret, "[REDACTED_CREDENTIAL]")
                    return re.sub(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=\r\n]+", "[REDACTED_IMAGE_DATA]", text)
                safe_raw = redact(raw_text) if raw_text is not None else None
                raw_path = self.artifact_dir / "raw" / (attempt_id + ".json")
                _write(raw_path, {"provider_mode": "live_api", "attempt_id": attempt_id,
                                  "http_status": status, "raw_response_text": safe_raw,
                                  "redacted": safe_raw != raw_text})
                usage = response.get("usage") if response else None
                record = {**attempt_common, "event": "attempt_finished", "http_status": status,
                          "status": "success" if failure is None else "error",
                          "error_type": type(failure).__name__ if failure else None,
                          "error": str(failure) if isinstance(failure, ProviderError) else None,
                          "elapsed_s": time.monotonic() - started, "reported_usage": usage,
                          "normalized_usage": normalize_usage(usage), "estimated_cost_usd": estimate_cost(usage, self.config.pricing),
                          "billed_this_run_usd": None, "raw_artifact": str(raw_path),
                          "will_retry": bool(failure and transient and attempt <= self.max_retries)}
                self._record(parse_json_object(redact(_json(record))))
            if failure is None:
                # Sanitize the cache too in case an endpoint echoed credentials/images.
                clean_response = parse_json_object(redact(_json(response)))
                _write(cache_path, {"cache_key": key, "provider_mode": "live_api", "response": clean_response})
                return result
            if transient and attempt <= self.max_retries:
                continue
            raise failure
        raise AssertionError("Unreachable")


class ReplayProvider(_Journal):
    """Consume explicitly supplied response files in order; never call the network.

    A file may contain a plain result object, a Chat Completions response, or this
    module's raw-response artifact. Each use is labeled replay with zero new API
    billing; historical usage is source_reported_usage, never live reported_usage.
    """
    def __init__(self, response_files: Sequence[Path], artifact_dir: Path | str):
        super().__init__(artifact_dir, "replay")
        self.response_files = tuple(Path(p) for p in response_files)
        self._position = 0

    def complete(self, stage: str, prompt: str, images: Sequence[Path] = (), schema: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._position >= len(self.response_files):
            raise ProviderError("Replay response files exhausted")
        source = self.response_files[self._position]
        response = parse_json_object(source.read_text(encoding="utf-8"))
        if "raw_response_text" in response:
            response = parse_json_object(response["raw_response_text"])
        data = _response_data(response) if "choices" in response else response
        self._record({"event": "replay", "stage": stage, "source_file": str(source.resolve()),
                      "source_reported_usage": response.get("usage") if "choices" in response else None,
                      "reported_usage": None, "live_request": False, "estimated_cost_usd": 0.0,
                      "billed_this_run_usd": 0.0})
        self._position += 1
        return data


class ExchangeProvider(_Journal):
    """File exchange for an external assistant worker, explicitly not a live API.

    First call writes <hash>.request.json and raises PendingResponse. The worker
    writes a plain finite JSON object to <hash>.response.json. Resume with identical
    inputs. Any cost/usage of the external worker is unknown here. No response is
    trusted to supply API accounting. Images are referenced by absolute paths.
    """
    def __init__(self, queue_dir: Path | str, artifact_dir: Path | str, *, max_calls: int = 100,
                 model_name: str = "external-assistant-worker"):
        super().__init__(artifact_dir, "external_exchange")
        if type(max_calls) is not int or max_calls < 0:
            raise ValueError("max_calls must be a nonnegative integer")
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.max_calls = max_calls
        self.model_name = model_name
        self._requested: set[str] = set()
        self._consumed: set[str] = set()
        self._requested.update(p.name[:-len('.request.json')] for p in self.queue_dir.glob('*.request.json'))
        for record in self.records:
            if record.get('event') in {'external_exchange_pending','external_exchange','supplied_response_cache'}:
                if record.get('cache_key'):
                    self._requested.add(record['cache_key'])
                    if record['event']!='external_exchange_pending':self._consumed.add(record['cache_key'])

    def complete(self, stage: str, prompt: str, images: Sequence[Path] = (), schema: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata, _ = _image_inputs(images)
        if schema is not None:
            parse_json_object(_json(schema))
        identity = {"version": 1, "provider_mode": "external_exchange", "model": self.model_name,
                    "stage": stage, "prompt": prompt, "images": metadata, "schema": schema}
        key = _digest(identity)
        request_path = self.queue_dir / (key + ".request.json")
        response_path = self.queue_dir / (key + ".response.json")
        common = {"stage": stage, "model": self.model_name, "cache_key": key, "reported_usage": None,
                  "estimated_cost_usd": None, "billed_this_run_usd": None, "live_request": False}
        if key not in self._requested:
            if len(self._requested) >= self.max_calls:
                raise BudgetExceeded("Maximum external exchange requests reached")
            self._requested.add(key)
        if not request_path.exists():
            _write(request_path, {**identity, "cache_key": key, "image_paths": [str(Path(p).resolve()) for p in images],
                                  "response_path": str(response_path.resolve()),
                                  "instructions": "Write only a finite JSON object to response_path; do not execute model-generated code."})
        if not response_path.exists():
            self._record({**common, "event": "external_exchange_pending", "request_path": str(request_path)})
            raise PendingResponse(request_path, response_path)
        data = parse_json_object(response_path.read_text(encoding="utf-8"))
        cached = key in self._consumed
        self._record({**common, "event": "supplied_response_cache" if cached else "external_exchange",
                      "raw_artifact": str(response_path), "request_path": str(request_path)})
        self._consumed.add(key)
        return data
