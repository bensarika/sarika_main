"""Local HTTP tests exercise billing attribution without paid API calls."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from chart_harness.provider import (
    BudgetExceeded, ExchangeProvider, InvalidResponse, ModelConfig, PendingResponse,
    Provider, ProviderError, ReplayProvider, estimate_cost, measures, normalize_usage,
    parse_json_object,
)


def completion(content='{"ok": true}', usage=None, **overrides):
    result = {"id": "stub-result", "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    if usage is not None:
        result["usage"] = usage
    result.update(overrides)
    return result


FULL_USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
              "prompt_tokens_details": {"cached_tokens": 40},
              "completion_tokens_details": {"reasoning_tokens": 5}, "vendor_field": "preserved"}


@contextmanager
def stub_server(responses):
    """Responses are (HTTP status, JSON object or literal text)."""
    received = []
    queue = list(responses)
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "body": json.loads(body), "headers": dict(self.headers)})
            code, response = queue.pop(0) if queue else (500, {"error": "unexpected extra request"})
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write((response if isinstance(response, str) else json.dumps(response)).encode())
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def dribbling_server(stop):
    """Sends headers, then one byte at a time until the client gives up."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            while not stop.is_set():
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except OSError:
                    return
                stop.wait(.05)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def asking(name, arguments, call_id="call-1"):
    """A reply that stops to ask Python to measure something."""
    return {"id": "stub-ask", "choices": [{"finish_reason": "tool_calls", "message": {
        "content": None, "tool_calls": [{"id": call_id, "type": "function",
                                         "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}


class Measured:
    """A stand-in for the figure: records what was asked, answers plainly."""
    def __init__(self, answer=None):
        self.asked = []
        self.answer = answer if answer is not None else {"ink_fraction": .8, "would_be_kept": True}

    def run(self, name, arguments):
        self.asked.append((name, arguments))
        return self.answer


class ReadersThatMeasureFirst(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.tools = [{"type": "function", "function": {
            "name": "measure_ink_at", "description": "measure",
            "parameters": {"type": "object", "properties": {"x": {"type": "number"}}}}}]

    def test_an_ask_is_measured_and_the_conversation_carries_on_to_the_answer(self):
        figure = Measured()
        with stub_server([(200, asking("measure_ink_at", {"x": 12})),
                          (200, completion('{"series": ["a"]}'))]) as (url, calls):
            provider = Provider(ModelConfig("arbitrary/user-model", url), self.root)
            result = provider.complete("interpret", "prompt", tools=self.tools, tool_runner=figure)
        self.assertEqual({"series": ["a"]}, result)
        self.assertEqual([("measure_ink_at", {"x": 12})], figure.asked)
        answered = calls[1]["body"]["messages"][-1]
        self.assertEqual("tool", answered["role"])
        self.assertEqual("call-1", answered["tool_call_id"])
        self.assertTrue(json.loads(answered["content"])["would_be_kept"])

    def test_the_measurements_are_offered_with_the_prompt(self):
        with stub_server([(200, completion())]) as (url, calls):
            provider = Provider(ModelConfig("arbitrary/user-model", url), self.root)
            provider.complete("interpret", "prompt", tools=self.tools, tool_runner=Measured())
        self.assertEqual(["measure_ink_at"], [t["function"]["name"] for t in calls[0]["body"]["tools"]])
        self.assertEqual("auto", calls[0]["body"]["tool_choice"])

    def test_a_reader_that_only_measures_is_made_to_answer_rather_than_loop(self):
        figure = Measured()
        rounds = 2
        replies = [(200, asking("measure_ink_at", {"x": n})) for n in range(rounds)]
        with stub_server([*replies, (200, completion('{"series": []}'))]) as (url, calls):
            provider = Provider(ModelConfig("arbitrary/user-model", url, max_tool_rounds=rounds), self.root)
            result = provider.complete("interpret", "prompt", tools=self.tools, tool_runner=figure)
        self.assertEqual({"series": []}, result)
        self.assertEqual(rounds, len(figure.asked))
        last = calls[-1]["body"]
        self.assertNotIn("tools", last)
        self.assertIn("Answer now", last["messages"][-1]["content"])

    def test_a_failed_measurement_is_answered_and_the_reading_continues(self):
        class Breaks:
            def run(self, name, arguments):
                raise RuntimeError("that region is off the page")
        with stub_server([(200, asking("measure_ink_at", {"x": 12})),
                          (200, completion('{"series": ["a"]}'))]) as (url, calls):
            provider = Provider(ModelConfig("arbitrary/user-model", url), self.root)
            result = provider.complete("interpret", "prompt", tools=self.tools, tool_runner=Breaks())
        self.assertEqual({"series": ["a"]}, result)
        self.assertIn("off the page", json.loads(calls[1]["body"]["messages"][-1]["content"])["error"])

    def test_a_turn_that_may_be_a_question_is_not_forced_into_json(self):
        """Demanding an object of a turn that wants to ask makes it write the ask as prose."""
        figure = Measured()
        with stub_server([(200, asking("measure_ink_at", {"x": 12})),
                          (200, completion('{"series": []}'))]) as (url, calls):
            provider = Provider(ModelConfig("arbitrary/user-model", url, json_mode=True,
                                            max_tool_rounds=1), self.root)
            provider.complete("interpret", "prompt", tools=self.tools, tool_runner=figure)
        offered, final = calls[0]["body"], calls[-1]["body"]
        self.assertIn("tools", offered)
        self.assertNotIn("response_format", offered)
        self.assertNotIn("tools", final)
        self.assertEqual({"type": "json_object"}, final["response_format"])

    def test_an_endpoint_that_cannot_carry_questions_is_not_given_tools(self):
        chatting = Provider(ModelConfig("arbitrary/user-model", "https://example.invalid/v1"), self.root)
        other = Provider(ModelConfig("arbitrary/user-model", "https://example.invalid/v1",
                                     wire_api="responses"), self.root)
        self.assertTrue(measures(chatting))
        self.assertFalse(measures(other))
        self.assertFalse(measures(object()))

    def test_tools_offered_with_nothing_to_run_them_is_a_mistake(self):
        provider = Provider(ModelConfig("arbitrary/user-model", "https://example.invalid/v1"), self.root)
        with self.assertRaises(ValueError):
            provider.complete("interpret", "prompt", tools=self.tools)


class ProviderTests(unittest.TestCase):
    def test_timeout_bounds_the_whole_response_not_just_the_socket(self):
        stop = threading.Event()
        self.addCleanup(stop.set)
        with dribbling_server(stop) as url:
            provider = Provider(ModelConfig("arbitrary/user-model", url, timeout_s=1), self.root)
            started = time.monotonic()
            with self.assertRaises(ProviderError) as caught:
                provider.complete("interpret", "prompt")
            self.assertLess(time.monotonic() - started, 20)
        self.assertIn("Transport failure", str(caught.exception))

    def test_a_call_cannot_outlive_the_runs_own_clock(self):
        # The per-call timeout is generous on purpose; the run's budget is not, and
        # a reader still talking when the run is over is of no use to it.
        stop = threading.Event()
        self.addCleanup(stop.set)
        with dribbling_server(stop) as url:
            provider = Provider(ModelConfig("arbitrary/user-model", url, timeout_s=600), self.root)
            provider.not_after = time.monotonic() + 1
            started = time.monotonic()
            with self.assertRaises(ProviderError):
                provider.complete("interpret", "prompt")
            self.assertLess(time.monotonic() - started, 20)

    def test_a_spent_budget_stops_the_request_before_it_is_sent(self):
        with stub_server([(200, completion())]) as (url, calls):
            provider = Provider(ModelConfig("arbitrary/user-model", url), self.root)
            provider.not_after = time.monotonic() - 1
            with self.assertRaises(ProviderError):
                provider.complete("interpret", "prompt")
            self.assertEqual([], calls)

    def test_reasoning_effort_is_sent_and_changes_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            with stub_server([(200, completion()), (200, completion())]) as (url, calls):
                for effort in ('high', 'low'):
                    provider = Provider(ModelConfig('muse-spark-1.3-contributor',url,reasoning_effort=effort),directory)
                    provider.complete('interpret','same prompt')
                self.assertEqual([c['body']['reasoning_effort'] for c in calls],['high','low'])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def events(self, provider, event):
        return [r for r in provider.records if r["event"] == event]

    def test_payload_stateless_usage_exact_and_reasoning_not_double_counted(self):
        with stub_server([(200, completion(usage=FULL_USAGE)), (200, completion(usage=FULL_USAGE))]) as (url, calls):
            config = ModelConfig("arbitrary/user-model", url, api_key_env="TEST_PROVIDER_KEY", json_mode=True,
                                 pricing={"input": 2.0, "cached": 0.5, "output": 10.0}, max_output_tokens=100)
            with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "private-test-credential"}):
                provider = Provider(config, self.root)
                self.assertEqual(provider.complete("perceive", "first"), {"ok": True})
                provider.complete("extract", "second")
            self.assertEqual(calls[0]["path"], "/v1/chat/completions")
            self.assertEqual(len(calls[1]["body"]["messages"]), 1)
            self.assertNotIn("first", calls[1]["body"]["messages"][0]["content"][0]["text"])
            self.assertEqual(calls[0]["body"]["max_completion_tokens"], 100)
            self.assertEqual(calls[0]["body"]["response_format"], {"type": "json_object"})
            self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer private-test-credential")
            finished = self.events(provider, "attempt_finished")
            self.assertEqual(finished[0]["reported_usage"], FULL_USAGE)
            self.assertEqual(finished[0]["normalized_usage"]["output_tokens"], 20)
            self.assertEqual(finished[0]["normalized_usage"]["reasoning_tokens"], 5)
            self.assertAlmostEqual(finished[0]["estimated_cost_usd"], 0.00034)
            self.assertEqual(provider.summary()["reported_known_token_subtotals"]["total_tokens"], 240)
            all_text = "\n".join(p.read_text() for p in self.root.rglob("*.json*"))
            self.assertNotIn("private-test-credential", all_text)

    def test_disk_cache_has_zero_new_billing_and_separate_source_usage(self):
        with stub_server([(200, completion(usage=FULL_USAGE))]) as (url, calls):
            config = ModelConfig("chosen-model", url)
            first = Provider(config, self.root / "first", cache_dir=self.root / "shared")
            first.complete("first-stage", "identical")
            second = Provider(config, self.root / "second", cache_dir=self.root / "shared", max_calls=0)
            self.assertEqual(second.complete("different-stage", "identical"), {"ok": True})
            self.assertEqual(len(calls), 1)
            record = self.events(second, "cache_hit")[0]
            self.assertIsNone(record["reported_usage"])
            self.assertEqual(record["source_reported_usage"], FULL_USAGE)
            self.assertEqual(record["billed_this_run_usd"], 0)
            self.assertEqual(second.summary()["live_attempts"], 0)

    def test_cache_key_changes_for_images_schema_and_model_settings(self):
        with stub_server([(200, completion())] * 4) as (url, calls):
            image = self.root / "image.png"
            image.write_bytes(b"first-image-bytes")
            provider = Provider(ModelConfig("m", url), self.root / "run")
            provider.complete("stage", "read", [image], {"type": "object"})
            image.write_bytes(b"second-image-bytes")
            provider.complete("stage", "read", [image], {"type": "object"})
            provider.complete("stage", "read", [image], {"type": "object", "required": ["x"]})
            other = Provider(ModelConfig("m", url, temperature=0.1), self.root / "run")
            other.complete("stage", "read", [image], {"type": "object"})
            self.assertEqual(len(calls), 4)
            self.assertTrue(calls[0]["body"]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertNotIn("base64", provider.usage_path.read_text())

    def test_missing_usage_is_unknown_and_cached_subset_absence_stays_unknown(self):
        with stub_server([(200, completion())]) as (url, _):
            provider = Provider(ModelConfig("m", url, pricing={"input": 1, "output": 2}), self.root)
            provider.complete("stage", "request")
            summary = provider.summary()
            self.assertIsNone(summary["estimated_cost_usd_total"])
            self.assertEqual(summary["unknown_cost_attempts"], 1)
            self.assertEqual(summary["unknown_token_attempt_counts"]["input_tokens"], 1)
        partial = {"prompt_tokens": 10, "completion_tokens": 3}
        self.assertIsNone(normalize_usage(partial)["cached_input_tokens"])
        self.assertIsNone(estimate_cost(partial, {"input": 1, "cached": 0.5, "output": 2}))
        self.assertAlmostEqual(estimate_cost(partial, {"input": 1, "output": 2}), 0.000016)

    def test_retry_is_opt_in_and_both_attempts_reserved_and_logged(self):
        responses = [(503, {"error": "unavailable"}), (200, completion(usage=FULL_USAGE))]
        with stub_server(responses) as (url, calls):
            provider = Provider(ModelConfig("m", url, max_output_tokens=30), self.root, max_retries=1)
            provider.complete("stage", "request")
            self.assertEqual(len(calls), 2)
            finished = self.events(provider, "attempt_finished")
            self.assertEqual(len(finished), 2)
            self.assertTrue(finished[0]["will_retry"])
            self.assertIsNone(finished[0]["reported_usage"])
            self.assertIsNone(finished[0]["billed_this_run_usd"])
            self.assertEqual(provider.summary()["reserved_output_tokens"], 60)
        with stub_server([(503, {"error": "unavailable"})]) as (url, calls):
            provider = Provider(ModelConfig("m", url), self.root / "no-retry")
            with self.assertRaises(ProviderError):
                provider.complete("stage", "request")
            self.assertEqual(len(calls), 1)

    def test_retry_cannot_bypass_attempt_or_output_budget(self):
        for constraints in ({"max_calls": 1}, {"max_reserved_output_tokens": 40}):
            with self.subTest(constraints=constraints), stub_server([(503, {"error": "busy"})]) as (url, calls):
                provider = Provider(ModelConfig("m", url, max_output_tokens=40), self.root / next(iter(constraints)), max_retries=1, **constraints)
                with self.assertRaises(BudgetExceeded):
                    provider.complete("stage", "request")
                self.assertEqual(len(calls), 1)

    def test_estimated_budget_checks_before_network_and_requires_prices(self):
        with stub_server([]) as (url, calls):
            with self.assertRaises(ValueError):
                Provider(ModelConfig("m", url), self.root, max_estimated_cost_usd=1)
            provider = Provider(ModelConfig("m", url, pricing={"input": 1, "output": 1}), self.root, max_estimated_cost_usd=0)
            with self.assertRaises(BudgetExceeded):
                provider.complete("stage", "request")
            self.assertEqual(calls, [])

    def test_invalid_json_is_not_retried_and_usage_still_recorded(self):
        for content in ('```json\n{"x": 1}\n```', '{"x": NaN}', '{"x": 1e999}', '{"x": 1, "x": 2}', '[1, 2]'):
            with self.subTest(content=content), stub_server([(200, completion(content, FULL_USAGE))]) as (url, calls):
                provider = Provider(ModelConfig("m", url), self.root / str(len(content)), max_retries=1)
                with self.assertRaises(InvalidResponse):
                    provider.complete("stage", "request")
                self.assertEqual(len(calls), 1)
                self.assertEqual(self.events(provider, "attempt_finished")[0]["reported_usage"], FULL_USAGE)

    def test_error_artifact_redacts_credential_and_image_echo(self):
        secret = "secret-should-not-appear"
        response = {"error": f"{secret} data:image/png;base64,c2VjcmV0"}
        with stub_server([(401, response)]) as (url, calls):
            provider = Provider(ModelConfig("m", url, api_key_env="STUB_KEY"), self.root, max_retries=1)
            with patch.dict(os.environ, {"STUB_KEY": secret}), self.assertRaises(ProviderError):
                provider.complete("stage", "request")
            self.assertEqual(len(calls), 1)
            artifacts = "\n".join(path.read_text() for path in self.root.rglob("*.json*"))
            self.assertNotIn(secret, artifacts)
            self.assertNotIn("c2VjcmV0", artifacts)
            self.assertIn("REDACTED", artifacts)

    def test_replay_is_explicit_and_never_live(self):
        source = self.root / "recorded.json"
        source.write_text(json.dumps(completion(usage=FULL_USAGE)))
        provider = ReplayProvider([source], self.root / "replay")
        self.assertEqual(provider.complete("stage", "unused"), {"ok": True})
        record = self.events(provider, "replay")[0]
        self.assertEqual(record["provider_mode"], "replay")
        self.assertIsNone(record["reported_usage"])
        self.assertEqual(record["source_reported_usage"], FULL_USAGE)
        self.assertEqual(provider.summary()["live_attempts"], 0)
        with self.assertRaises(ProviderError):
            provider.complete("stage", "unused")

    def test_external_exchange_request_resume_cache_and_unknown_cost(self):
        image = self.root / "chart.png"
        image.write_bytes(b"png-for-reference")
        provider = ExchangeProvider(self.root / "queue", self.root / "exchange", max_calls=1)
        with self.assertRaises(PendingResponse) as caught:
            provider.complete("perceive", "inspect chart", [image], {"type": "object"})
        manifest = json.loads(caught.exception.request_path.read_text())
        self.assertEqual(manifest["provider_mode"], "external_exchange")
        self.assertEqual(manifest["image_paths"], [str(image.resolve())])
        caught.exception.response_path.write_text('{"series": []}')
        self.assertEqual(provider.complete("perceive", "inspect chart", [image], {"type": "object"}), {"series": []})
        provider.complete("perceive", "inspect chart", [image], {"type": "object"})
        self.assertEqual(provider.summary()["exchange_calls"], 1)
        self.assertEqual(provider.summary()["supplied_response_cache_hits"], 1)
        self.assertIsNone(provider.summary()["estimated_cost_usd_total"])
        self.assertEqual(provider.summary()["live_attempts"], 0)
        with self.assertRaises(BudgetExceeded):
            provider.complete("second", "different")

    def test_config_and_json_validation(self):
        for url in ("https://secret@example.com", "https://example.com/v1?key=secret", "ftp://example.com"):
            with self.assertRaises(ValueError):
                ModelConfig("m", url)
        with self.assertRaises(InvalidResponse):
            parse_json_object('{"x": Infinity}')
        self.assertEqual(ModelConfig("m", "http://localhost:9999/v1/chat/completions/").endpoint,
                         "http://localhost:9999/v1/chat/completions")

    def test_resumed_process_cannot_reset_attempt_or_output_limits(self):
        for constraint in ({'max_calls':1},{'max_reserved_output_tokens':40}):
            directory=self.root/next(iter(constraint))
            with stub_server([(200,completion(usage=FULL_USAGE))]) as (url,calls):
                config=ModelConfig('m',url,max_output_tokens=40)
                first=Provider(config,directory,**constraint)
                first.complete('stage','first')
                resumed=Provider(config,directory,**constraint)
                self.assertEqual(resumed.summary()['live_attempts'],1)
                self.assertEqual(resumed.reserved_output_tokens,40)
                self.assertEqual(resumed.complete('stage','first'),{'ok':True})
                with self.assertRaises(BudgetExceeded):resumed.complete('stage','different')
                self.assertEqual(len(calls),1)

    def test_unfinished_attempt_reservation_survives_restart(self):
        event={'event':'attempt_started','attempt_id':'crashed','reserved_output_tokens':40,
               'estimated_reserved_cost_usd':0.25,'reported_usage':None}
        (self.root/'usage.jsonl').write_text(json.dumps(event)+'\n')
        with stub_server([]) as (url,calls):
            config=ModelConfig('m',url,max_output_tokens=40,pricing={'input':1,'output':1})
            resumed=Provider(config,self.root,max_estimated_cost_usd=0.25)
            self.assertEqual(resumed.live_attempts,1)
            self.assertEqual(resumed.reserved_output_tokens,40)
            self.assertEqual(resumed.summary()['unknown_cost_attempts'],1)
            with self.assertRaises(BudgetExceeded):resumed.complete('stage','new')
            self.assertEqual(calls,[])

    def test_exchange_identity_and_budget_survive_restart(self):
        queue=self.root/'queue';journal=self.root/'journal'
        first=ExchangeProvider(queue,journal,max_calls=1)
        with self.assertRaises(PendingResponse) as pending:first.complete('stage','read')
        resumed=ExchangeProvider(queue,journal,max_calls=1)
        with self.assertRaises(BudgetExceeded):resumed.complete('stage','different')
        pending.exception.response_path.write_text('{"ok":true}')
        resumed.complete('stage','read')
        again=ExchangeProvider(queue,journal,max_calls=1)
        again.complete('stage','read')
        self.assertEqual(again.summary()['exchange_calls'],1)
        self.assertEqual(again.summary()['supplied_response_cache_hits'],1)
        self.assertEqual(again.summary()['unknown_token_attempt_counts']['input_tokens'],1)


if __name__ == "__main__":
    unittest.main()
