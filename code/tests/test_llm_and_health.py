"""The model client and the run's health signals.

Neither touches the network here. The client's transport is replaced, because what needs
testing is what the code does around a call -- the cache key, the refusal to guess at a
malformed reply, the ledger that the usage report is built from, and the fact that no key
ever reaches disk -- not whether a provider answers.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit import evidence, health, llm  # noqa: E402

#: A fixture, deliberately NOT shaped like a real key.
#:
#: It was `sk-` followed by filler, and the submission packager's secret scan stopped the
#: build over it. The scan was right: nothing reading a file can tell a convincing fake
#: from the real thing, and a string shaped like a credential has no business travelling
#: inside a submission. The test still needs a distinctive value to search the cache for,
#: so it has one that cannot be mistaken for a key.
KEY = "TEST-CREDENTIAL-PLACEHOLDER-NEVER-REAL"


class _Scripted(llm.Client):
    """A client whose transport returns canned replies and counts what it was asked."""

    def __init__(self, replies, **kwargs):
        self.replies = list(replies)
        self.asked: list[dict] = []
        super().__init__(**kwargs)

    def _post(self, payload):
        self.asked.append(payload)
        if not self.replies:
            raise llm.LLMError("no reply scripted")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, 11, 7


def _client(replies, **kwargs):
    import os
    os.environ["OPENAI_API_KEY"] = KEY
    cache = Path(tempfile.mkdtemp())
    return _Scripted(replies, provider="openai", cache_dir=cache, retries=1, **kwargs)


class Ledger(unittest.TestCase):
    def test_cost_follows_the_published_price(self):
        cost = llm.Usage.cost_of("gpt-4o-mini", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 0.15 + 0.60, places=6)

    def test_an_unpriced_model_costs_zero_rather_than_guessing(self):
        self.assertEqual(llm.Usage.cost_of("some-model-we-never-priced", 10, 10), 0.0)

    def test_every_default_model_has_a_price(self):
        for _env, _url, text_model, vision_model in llm.PROVIDERS.values():
            for model in (text_model, vision_model):
                with self.subTest(model=model):
                    self.assertIn(model, llm.PRICES)

    def test_calls_accumulate_per_model_and_overall(self):
        usage = llm.Usage()
        usage.record("gpt-4o-mini", "openai", 100, 50, 0.1)
        usage.record("gpt-4o-mini", "openai", 200, 20, 0.2)
        self.assertEqual(usage.calls, 2)
        self.assertEqual(usage.input_tokens, 300)
        self.assertEqual(usage.output_tokens, 70)
        self.assertEqual(usage.per_model["gpt-4o-mini"]["calls"], 2)
        self.assertGreater(usage.cost_usd, 0)


class Calling(unittest.TestCase):
    def test_a_reply_is_returned_and_counted(self):
        client = _client(['{"ok": true}'])
        self.assertEqual(client.ask("sys", "user"), '{"ok": true}')
        self.assertEqual(client.usage.calls, 1)
        self.assertEqual(client.usage.input_tokens, 11)

    def test_the_same_prompt_is_served_from_cache(self):
        client = _client(['{"ok": true}'])
        client.ask("sys", "user")
        client.ask("sys", "user")
        self.assertEqual(len(client.asked), 1)
        self.assertEqual(client.usage.cached, 1)

    def test_a_different_prompt_is_a_different_key(self):
        client = _client(['{"a": 1}', '{"b": 2}'])
        self.assertNotEqual(client.ask("sys", "one"), client.ask("sys", "two"))
        self.assertEqual(len(client.asked), 2)

    def test_the_temperature_is_part_of_the_key(self):
        client = _client(['{"a": 1}', '{"b": 2}'])
        client.ask("sys", "user", temperature=0.0)
        client.ask("sys", "user", temperature=0.7)
        self.assertEqual(len(client.asked), 2)

    def test_temperature_defaults_to_zero(self):
        # Every measurement in this repository assumes the same input answers twice.
        client = _client(['{"a": 1}'])
        client.ask("sys", "user")
        self.assertEqual(client.asked[0]["temperature"], 0.0)

    def test_no_api_key_ever_reaches_the_cache(self):
        client = _client(['{"ok": true}'])
        client.ask("sys", "user")
        for path in client.cache_dir.glob("*.json"):
            with self.subTest(file=path.name):
                self.assertNotIn(KEY, path.read_text(encoding="utf-8"))

    def test_a_failure_raises_rather_than_returning_a_guess(self):
        client = _client([llm.LLMError("boom")])
        with self.assertRaises(llm.LLMError):
            client.ask("sys", "user")
        self.assertEqual(client.usage.failures, 1)

    def test_a_failed_call_is_not_cached(self):
        client = _client([llm.LLMError("boom")])
        with self.assertRaises(llm.LLMError):
            client.ask("sys", "user")
        self.assertEqual(list(client.cache_dir.glob("*.json")), [])

    def test_json_is_parsed_through_a_code_fence(self):
        client = _client(['```json\n{"authorises_deletion": true}\n```'])
        self.assertEqual(client.ask_json("sys", "user"),
                         {"authorises_deletion": True})

    def test_json_is_parsed_out_of_surrounding_prose(self):
        client = _client(['Sure! {"n": 1} hope that helps'])
        self.assertEqual(client.ask_json("sys", "user"), {"n": 1})

    def test_a_reply_with_no_json_raises(self):
        client = _client(["I would rather not answer."])
        with self.assertRaises(llm.LLMError):
            client.ask_json("sys", "user")

    def test_malformed_json_raises_rather_than_being_repaired(self):
        client = _client(['{"n": 1,,,}'])
        with self.assertRaises(llm.LLMError):
            client.ask_json("sys", "user")

    def test_a_missing_key_is_refused_at_construction(self):
        import os
        saved = {name: os.environ.pop(env, None)
                 for name, (env, *_r) in llm.PROVIDERS.items()
                 for env in [llm.PROVIDERS[name][0]]}
        try:
            with self.assertRaises(llm.LLMError):
                llm.Client()
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[llm.PROVIDERS[name][0]] = value


class HealthSignals(unittest.TestCase):
    def test_a_maximum_alerts_above_and_a_minimum_below(self):
        self.assertTrue(health.Signal("a", 2, 1, "max").breached)
        self.assertFalse(health.Signal("a", 0.5, 1, "max").breached)
        self.assertTrue(health.Signal("b", 0.5, 1, "min").breached)
        self.assertFalse(health.Signal("b", 2, 1, "min").breached)

    def test_a_signal_without_a_limit_is_reported_not_alerted(self):
        self.assertFalse(health.Signal("c", 10_000).breached)

    def test_the_document_is_json_and_says_whether_it_is_healthy(self):
        report = health.Health()
        report.add("fine", 1, limit=2)
        document = json.loads(json.dumps(report.as_dict()))
        self.assertTrue(document["healthy"])
        report.add("bad", 5, limit=2)
        self.assertFalse(report.as_dict()["healthy"])
        self.assertEqual([s.name for s in report.breaches], ["bad"])

    def test_a_rise_in_complete_verdicts_is_watched(self):
        # The signal that would catch this system failing the way the story describes.
        report = health.measure(_verdicts(complete=90, incomplete=10),
                                _reader(), None, range(100))
        rate = next(s for s in report.signals if s.name == "complete_rate")
        self.assertIsNotNone(rate.limit)
        self.assertTrue(rate.breached, "90% COMPLETE should not look healthy")

    def test_an_ordinary_run_is_healthy(self):
        report = health.measure(_verdicts(complete=40, incomplete=60),
                                _reader(), None, range(100))
        self.assertEqual(report.breaches, [])

    def test_an_unreadable_file_alerts_but_an_empty_one_does_not(self):
        reader = _reader()
        reader.accounted = [("evidence_1", "read; names no auditable resource")] * 5
        healthy = health.measure(_verdicts(complete=40, incomplete=60), reader, None,
                                 range(100))
        self.assertEqual(healthy.breaches, [])

        reader.unread = [("evidence_2", "could not parse")]
        alerted = health.measure(_verdicts(complete=40, incomplete=60), reader, None,
                                 range(100))
        self.assertEqual([s.name for s in alerted.breaches], ["evidence_files_unread"])


class _FakeVerdict:
    def __init__(self, status, notes=(), steps=(1,)):
        self.status, self.notes, self.steps = status, list(notes), list(steps)


def _verdicts(*, complete: int, incomplete: int):
    return ([_FakeVerdict("COMPLETE") for _ in range(complete)]
            + [_FakeVerdict("INCOMPLETE") for _ in range(incomplete)])


class _FakeReader:
    def __init__(self):
        self.unread: list = []
        self.accounted: list = []
        self.observations = [
            evidence.Observation(file_id="evidence_1",
                                 captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                                 resource_id="account_1", system_id="account_service")
        ] * 2000
        self.coverage: list = []


def _reader():
    return _FakeReader()


if __name__ == "__main__":
    unittest.main()
