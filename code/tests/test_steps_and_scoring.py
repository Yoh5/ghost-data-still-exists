"""The step vocabulary, the ordering the spec fixes, and the scorer itself.

These two are tested together because they are each other's check: the serialiser decides
what order means, and the scorer decides whether order was achieved. A bug shared between
them would be invisible from either side, so the serialiser is tested against the
published answers and the scorer against hand-built cases.
"""
from __future__ import annotations

import json
import random
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit import dataset, scoring, steps  # noqa: E402


class StepVocabulary(unittest.TestCase):
    def test_phase_and_state_are_functions_of_the_operation(self):
        # The spec's table never gives one operation two states. If that stops being
        # true, carrying them separately becomes necessary again.
        for operation, (phase, state) in steps.OPERATIONS.items():
            step = steps.Step(operation, "account_service", "account_1")
            self.assertEqual(step.phase, phase)
            self.assertEqual(step.state, state)

    def test_an_invented_operation_is_refused(self):
        with self.assertRaises(steps.StepError):
            steps.Step("PURGE_EVERYTHING", "account_service", "account_1")

    def test_an_empty_resource_is_refused(self):
        with self.assertRaises(steps.StepError):
            steps.Step("DELETE_RECORD", "account_service", "")

    def test_duplicate_steps_are_refused(self):
        # Emitting the same step twice would shift every following step_no.
        pair = [steps.Step("DELETE_RECORD", "search_service", "search_1")] * 2
        with self.assertRaises(steps.StepError):
            steps.serialise(pair)

    def test_serialised_steps_carry_exactly_the_seven_required_fields(self):
        out = steps.serialise([steps.Step("DELETE_RECORD", "search_service", "search_1")])
        self.assertEqual(set(out[0]), set(steps.FIELDS))

    def test_numbering_is_consecutive_from_one(self):
        made = [steps.Step("VERIFY_RECORD_ABSENT", "search_service", f"search_{i}")
                for i in range(5)]
        out = steps.serialise(made)
        self.assertEqual([s["step_no"] for s in out], [1, 2, 3, 4, 5])

    def test_phases_come_in_the_order_the_spec_fixes(self):
        out = steps.serialise([
            steps.Step("VERIFY_RECORD_ABSENT", "search_service", "search_1"),
            steps.Step("DELETE_RECORD", "search_service", "search_1"),
            steps.Step("REPORT_REMAINING_RECORD", "search_service", "search_1"),
        ])
        self.assertEqual([s["phase"] for s in out],
                         ["FINDING", "REMEDIATION", "VERIFICATION"])

    def test_within_a_phase_operations_follow_the_table_then_system_then_resource(self):
        out = steps.serialise([
            steps.Step("REPORT_EXPOSED_PII", "support_platform", "support_9"),
            steps.Step("REPORT_EXPOSED_PII", "analytics_platform", "analytics_9"),
            steps.Step("REPORT_REMAINING_RECORD", "search_service", "search_9"),
        ])
        self.assertEqual([s["resource_id"] for s in out],
                         ["search_9", "analytics_9", "support_9"])

    def test_remediation_disables_flows_before_touching_records(self):
        # The ordering requirement that carries the actual safety meaning: stopping a
        # sync after deleting the record it feeds is the bug in the problem statement.
        out = steps.serialise([
            steps.Step("DELETE_RECORD", "search_service", "search_1"),
            steps.Step("DISABLE_DATA_FLOW", "integration_service", "data_flow_1"),
            steps.Step("BLOCK_RESTORE", "backup_service", "backup_1"),
        ])
        self.assertEqual([s["operation"] for s in out],
                         ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD"])


class OrderingAgainstThePublishedAnswers(unittest.TestCase):
    """Measurement M1, as a test rather than a note."""

    @classmethod
    def setUpClass(cls):
        _, cls.gold = dataset.load_samples()

    def test_every_published_order_is_reproduced_from_its_own_steps(self):
        rng = random.Random(7)
        for case_id, (_, published) in sorted(self.gold.items()):
            with self.subTest(case=case_id):
                shuffled = list(published)
                rng.shuffle(shuffled)
                self.assertEqual(steps.serialise(steps.parse(shuffled)), published)

    def test_every_published_step_uses_an_allowed_operation(self):
        for case_id, (_, published) in self.gold.items():
            for step in published:
                with self.subTest(case=case_id, op=step["operation"]):
                    self.assertIn(step["operation"], steps.OPERATIONS)
                    phase, state = steps.OPERATIONS[step["operation"]]
                    self.assertEqual(step["phase"], phase)
                    self.assertEqual(step["state"], state)


class Scorer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.gold = dataset.load_samples()

    def test_the_answers_scored_against_themselves_are_perfect(self):
        report = scoring.score(dict(self.gold), self.gold)
        for name in ("status_accuracy", "sequence_accuracy", "step_f1",
                     "field_accuracy", "evidence_accuracy"):
            self.assertEqual(getattr(report, name), 1.0, name)

    def test_shuffling_breaks_sequence_but_not_step_f1(self):
        rng = random.Random(3)
        shuffled = {}
        for case_id, (status, published) in self.gold.items():
            order = list(published)
            rng.shuffle(order)
            shuffled[case_id] = (status, order)
        report = scoring.score(shuffled, self.gold)
        self.assertEqual(report.step_f1, 1.0)
        self.assertLess(report.sequence_accuracy, 0.5)

    def test_a_missing_case_counts_as_a_total_miss_and_is_not_skipped(self):
        partial = dict(self.gold)
        dropped = sorted(partial)[0]
        del partial[dropped]
        report = scoring.score(partial, self.gold)
        self.assertEqual(report.n_cases, len(self.gold))
        self.assertLess(report.status_accuracy, 1.0)

    def test_extra_steps_cost_precision_not_recall(self):
        case_id = sorted(self.gold)[0]
        status, published = self.gold[case_id]
        noisy = list(published) + [dict(published[0], step_no=99,
                                        resource_id="search_99999",
                                        operation="VERIFY_RECORD_ABSENT",
                                        phase="VERIFICATION", state="ABSENT")]
        report = scoring.score({case_id: (status, noisy)}, {case_id: (status, published)})
        self.assertEqual(report.step_recall, 1.0)
        self.assertLess(report.step_precision, 1.0)

    def test_evidence_is_scored_apart_from_the_step_itself(self):
        case_id = next(c for c, (_, s) in self.gold.items()
                       if any(x["evidence_id"] for x in s))
        status, published = self.gold[case_id]
        wrong = [dict(s, evidence_id="evidence_nonexistent" if s["evidence_id"] else "")
                 for s in published]
        report = scoring.score({case_id: (status, wrong)},
                               {case_id: (status, published)})
        self.assertEqual(report.step_f1, 1.0)          # same records found
        self.assertEqual(report.evidence_accuracy, 0.0)  # all citations wrong


if __name__ == "__main__":
    unittest.main()
