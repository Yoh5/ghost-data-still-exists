"""The verdict, and the file that carries it.

The engine is tested on constructed situations rather than on the supplied data, so each
rule can be exercised on its own. The output is then tested on the real 518 rows, because
the submission contract is a property of the file, not of the objects that produced it.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit import dataset, engine, evidence, identity, inventory, policy  # noqa: E402
import main as agent  # noqa: E402

WHEN = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class _FixedInventory:
    """An inventory that returns exactly what a test asks for."""

    def __init__(self, candidates: dict[str, inventory.Candidate]) -> None:
        self.candidates = candidates

    def resources_for(self, subject, audit_at):            # noqa: ARG002
        return self.candidates


def _request(**kwargs):
    base = dict(case_id="case_test", email="someone@example.com", requested_at=WHEN,
                reported_status="COMPLETE", reported_at=WHEN, audit_at=WHEN,
                request_text="Please delete my account and personal data.")
    base.update(kwargs)
    return dataset.Request(**base)


def _candidate(resource_id, system_id, *, state=None, pii=None, flags=None,
               category="", via="evidence", file_id="evidence_x"):
    obs = evidence.Observation(file_id=file_id, captured_at=WHEN,
                               resource_id=resource_id, system_id=system_id,
                               category=category, present=state, reader="snapshot_bundle")
    if pii:
        for field, value in pii.items():
            obs.add_pii(field, value)
    if flags:
        obs.flags.update(flags)
    cand = inventory.Candidate(resource_id=resource_id, system_id=system_id, via=via)
    cand.observations = [obs]
    return cand


class Verdicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dataset.load()
        cls.index = identity.IdentityIndex(cls.data)
        cls.reader = evidence.EvidenceReader(cls.data)
        cls.policy = policy.Policy(cls.data)
        cls.subject = cls.index.resolve(cls.data.requests[0].email)

    def _audit(self, candidates, *, authorises=True, request=None):
        auditor = engine.Auditor(
            self.data, self.index, self.reader, _FixedInventory(candidates),
            self.policy, authorizes_deletion=lambda _r: authorises,
            policy_source="rules-first")
        email = self.data.requests[0].email
        return auditor.audit(request or _request(email=email))

    def test_a_non_deletion_request_produces_an_empty_plan(self):
        verdict = self._audit({}, authorises=False)
        self.assertEqual(verdict.status, engine.NOT_APPLICABLE)
        self.assertEqual(verdict.steps, [])

    def test_nothing_outstanding_is_complete(self):
        cand = _candidate("account_1", "account_service", state=False,
                          category="USER_PROFILE")
        verdict = self._audit({"account_1": cand})
        self.assertEqual(verdict.status, engine.COMPLETE)
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["VERIFY_RECORD_ABSENT"])

    def test_a_remaining_record_makes_the_case_incomplete(self):
        cand = _candidate("search_1", "search_service", state=True,
                          category="SEARCH_INDEX_ENTRY",
                          pii={"email": "someone@example.com"})
        verdict = self._audit({"search_1": cand})
        self.assertEqual(verdict.status, engine.INCOMPLETE)
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["REPORT_REMAINING_RECORD", "DELETE_RECORD",
                          "VERIFY_RECORD_ABSENT"])

    def test_every_finding_gets_exactly_one_remediation(self):
        cands = {
            "search_1": _candidate("search_1", "search_service", state=True,
                                   category="SEARCH_INDEX_ENTRY",
                                   pii={"email": "a@b.c"}),
            "analytics_1": _candidate("analytics_1", "analytics_platform", state=True,
                                      category="ANALYTICS_PROFILE",
                                      pii={"email": "a@b.c"}),
        }
        verdict = self._audit(cands)
        findings = {s["resource_id"] for s in verdict.steps if s["phase"] == "FINDING"}
        remedies = {s["resource_id"] for s in verdict.steps
                    if s["phase"] == "REMEDIATION"}
        self.assertEqual(findings, remedies)

    def test_verification_also_covers_what_needed_no_remediation(self):
        cands = {
            "search_1": _candidate("search_1", "search_service", state=True,
                                   category="SEARCH_INDEX_ENTRY",
                                   pii={"email": "a@b.c"}),
            "audit_record_1": _candidate("audit_record_1", "security_service",
                                         state=True, category="SECURITY_AUDIT_LOG"),
        }
        verdict = self._audit(cands)
        verified = {s["resource_id"] for s in verdict.steps
                    if s["phase"] == "VERIFICATION"}
        self.assertIn("audit_record_1", verified)
        self.assertNotIn("audit_record_1",
                         {s["resource_id"] for s in verdict.steps
                          if s["phase"] == "FINDING"})

    def test_a_retained_record_is_never_reported_as_a_violation(self):
        cand = _candidate("audit_record_1", "security_service", state=True,
                          category="SECURITY_AUDIT_LOG")
        verdict = self._audit({"audit_record_1": cand})
        self.assertEqual(verdict.status, engine.COMPLETE)
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["VERIFY_RECORD_PRESENT"])

    def test_an_active_data_flow_blocks_completion(self):
        cand = _candidate("data_flow_1", "integration_service", state=True,
                          category="DATA_FLOW", flags={"enabled": "true"})
        verdict = self._audit({"data_flow_1": cand})
        self.assertEqual(verdict.status, engine.INCOMPLETE)
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW",
                          "VERIFY_DATA_FLOW_DISABLED"])

    def test_a_restorable_backup_blocks_completion(self):
        cand = _candidate("backup_1", "backup_service", state=True,
                          category="BACKUP_ARCHIVE", flags={"restore_allowed": "1"})
        verdict = self._audit({"backup_1": cand})
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                          "VERIFY_RESTORE_BLOCKED"])

    def test_a_backup_of_unknown_status_counts_as_a_restore_risk(self):
        # "No active restore path can recreate the data" is not satisfied by an unknown.
        cand = _candidate("backup_1", "backup_service", state=None,
                          category="BACKUP_ARCHIVE")
        verdict = self._audit({"backup_1": cand})
        self.assertEqual(verdict.status, engine.INCOMPLETE)
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                          "VERIFY_RESTORE_BLOCKED"])

    def test_a_backup_known_to_be_blocked_is_only_verified(self):
        cand = _candidate("backup_1", "backup_service", state=True,
                          category="BACKUP_ARCHIVE", flags={"restore_allowed": "false"})
        verdict = self._audit({"backup_1": cand})
        self.assertEqual(verdict.status, engine.COMPLETE)
        self.assertEqual([s["operation"] for s in verdict.steps],
                         ["VERIFY_RESTORE_BLOCKED"])

    def test_the_latest_evidence_that_settles_a_state_wins(self):
        # A later observation that says nothing must not bury an earlier one that does.
        cand = _candidate("backup_1", "backup_service", state=True,
                          category="BACKUP_ARCHIVE", flags={"restore_allowed": "1"})
        silent = evidence.Observation(
            file_id="evidence_later", captured_at=WHEN + timedelta(days=2),
            resource_id="backup_1", system_id="backup_service", reader="log")
        cand.observations.append(silent)
        state, proof = policy.observed_state(cand, "BACKUP_ARCHIVE")
        self.assertEqual(state, policy.ACTIVE)
        self.assertEqual(proof.file_id, "evidence_x")

    def test_an_unestablished_state_refuses_the_complete_verdict(self):
        cand = _candidate("search_1", "search_service", state=None,
                          category="SEARCH_INDEX_ENTRY")
        verdict = self._audit({"search_1": cand})
        self.assertEqual(verdict.status, engine.INCOMPLETE)
        self.assertTrue(verdict.notes)

    def test_an_unconfirmed_retention_is_noted_but_does_not_overturn_the_verdict(self):
        cand = _candidate("audit_record_1", "security_service", state=None,
                          category="SECURITY_AUDIT_LOG")
        verdict = self._audit({"audit_record_1": cand})
        self.assertEqual(verdict.status, engine.COMPLETE)
        self.assertTrue(any("retention" in n for n in verdict.notes))

    def test_an_unconfirmed_retention_still_gets_its_check(self):
        """A verification step is a check to RUN, not a claim about the state now.

        Policy says the record must still be there afterwards, so the check belongs in
        the plan even when we could not confirm it at the cutoff. It carries no
        citation, which is what the spec requires of future work.
        """
        cands = {
            "search_1": _candidate("search_1", "search_service", state=True,
                                   category="SEARCH_INDEX_ENTRY",
                                   pii={"email": "a@b.c"}),
            "audit_record_1": _candidate("audit_record_1", "security_service",
                                         state=None, category="SECURITY_AUDIT_LOG"),
        }
        verdict = self._audit(cands)
        self.assertEqual(verdict.status, engine.INCOMPLETE)
        checks = [s for s in verdict.steps
                  if s["operation"] == "VERIFY_RECORD_PRESENT"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["resource_id"], "audit_record_1")
        self.assertEqual(checks[0]["evidence_id"], "")
        self.assertTrue(any("retention" in n for n in verdict.notes))

    def test_an_unconfirmed_retention_is_dropped_from_a_complete_case(self):
        """Where a check would have to be cited, an uncitable one is not published."""
        cands = {
            "account_1": _candidate("account_1", "account_service", state=False,
                                    category="USER_PROFILE", file_id="evidence_42"),
            "audit_record_1": _candidate("audit_record_1", "security_service",
                                         state=None, category="SECURITY_AUDIT_LOG"),
        }
        verdict = self._audit(cands)
        self.assertEqual(verdict.status, engine.COMPLETE)
        self.assertEqual([s["resource_id"] for s in verdict.steps], ["account_1"])
        self.assertTrue(all(s["evidence_id"] for s in verdict.steps))

    def test_a_complete_case_cites_evidence_on_every_step(self):
        cand = _candidate("account_1", "account_service", state=False,
                          category="USER_PROFILE", file_id="evidence_42")
        verdict = self._audit({"account_1": cand})
        self.assertTrue(all(s["evidence_id"] for s in verdict.steps))

    def test_future_work_carries_no_citation(self):
        cand = _candidate("search_1", "search_service", state=True,
                          category="SEARCH_INDEX_ENTRY", pii={"email": "a@b.c"},
                          file_id="evidence_42")
        verdict = self._audit({"search_1": cand})
        for step in verdict.steps:
            with self.subTest(step=step["operation"]):
                if step["phase"] == "FINDING":
                    self.assertEqual(step["evidence_id"], "evidence_42")
                else:
                    self.assertEqual(step["evidence_id"], "")

    def test_an_unresolvable_identity_never_yields_complete(self):
        auditor = engine.Auditor(self.data, self.index, self.reader,
                                 _FixedInventory({}), self.policy,
                                 authorizes_deletion=lambda _r: True)
        verdict = auditor.audit(_request(email="nobody@example.invalid"))
        self.assertEqual(verdict.status, engine.INCOMPLETE)
        self.assertTrue(verdict.notes)

    def test_steps_are_numbered_consecutively_whatever_the_case(self):
        cands = {
            "search_1": _candidate("search_1", "search_service", state=True,
                                   category="SEARCH_INDEX_ENTRY",
                                   pii={"email": "a@b.c"}),
            "backup_1": _candidate("backup_1", "backup_service", state=True,
                                   category="BACKUP_ARCHIVE",
                                   flags={"restore_allowed": "1"}),
            "audit_record_1": _candidate("audit_record_1", "security_service",
                                         state=True, category="SECURITY_AUDIT_LOG"),
        }
        verdict = self._audit(cands)
        self.assertEqual([s["step_no"] for s in verdict.steps],
                         list(range(1, len(verdict.steps) + 1)))


class TheSubmissionFile(unittest.TestCase):
    """The contract, checked on a file rather than on objects in memory."""

    @classmethod
    def setUpClass(cls):
        cls.data = dataset.load()
        cls.auditor = agent.build(cls.data, classify_intent=False, read_images=False)
        cls.verdicts = [cls.auditor.audit(r) for r in cls.data.requests]
        cls.path = Path(tempfile.mkdtemp()) / "output.csv"
        agent.write_output(cls.path, cls.verdicts)
        with cls.path.open(encoding="utf-8", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_one_row_per_request_in_numeric_case_order(self):
        self.assertEqual(len(self.rows), len(self.data.requests))
        self.assertEqual([r["case_id"] for r in self.rows],
                         [r.case_id for r in self.data.requests])

    def test_lexicographic_order_would_have_been_wrong(self):
        # Guards the trap rather than the fix: case_100 sorts before case_33.
        ids = [r["case_id"] for r in self.rows]
        self.assertNotEqual(ids, sorted(ids))

    def test_the_columns_are_exactly_the_three_required(self):
        self.assertEqual(list(self.rows[0]), list(agent.COLUMNS))

    def test_every_status_is_one_of_the_three_allowed(self):
        allowed = {engine.COMPLETE, engine.INCOMPLETE, engine.NOT_APPLICABLE}
        self.assertTrue(all(r["deletion_status"] in allowed for r in self.rows))

    def test_every_plan_parses_as_json_and_numbers_from_one(self):
        for row in self.rows:
            with self.subTest(case=row["case_id"]):
                plan = json.loads(row["steps_json"])
                self.assertEqual([s["step_no"] for s in plan],
                                 list(range(1, len(plan) + 1)))

    def test_every_step_uses_an_allowed_operation_with_its_own_state(self):
        from audit import steps as step_module
        for row in self.rows:
            for step in json.loads(row["steps_json"]):
                with self.subTest(case=row["case_id"], op=step["operation"]):
                    phase, state = step_module.OPERATIONS[step["operation"]]
                    self.assertEqual(step["phase"], phase)
                    self.assertEqual(step["state"], state)
                    self.assertEqual(set(step), set(step_module.FIELDS))

    def test_the_file_has_no_doubled_line_endings(self):
        """Without newline="" on Windows the csv module's own CR LF is doubled.

        The first version of this test looked for CR LF CR LF, which is not what
        the fault produces: the translation layer turns the writer's LF into CR LF,
        so each row ends CR CR LF. The mutation harness caught the test looking for
        the wrong symptom -- the fault was real and the assertion missed it.
        """
        raw = self.path.read_bytes()
        doubled = bytes([13, 13, 10])      # CR CR LF
        blank = bytes([13, 10, 13, 10])    # CR LF CR LF
        self.assertNotIn(doubled, raw)
        self.assertNotIn(blank, raw)

    def test_reading_the_file_back_yields_no_empty_rows(self):
        with self.path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertTrue(all(row for row in rows), "a blank row reached the file")
    def test_the_contract_check_accepts_what_we_wrote(self):
        agent.check_output(self.path, len(self.data.requests))

    def test_the_contract_check_rejects_a_truncated_file(self):
        short = self.path.with_name("short.csv")
        agent.write_output(short, self.verdicts[:10])
        with self.assertRaises(SystemExit):
            agent.check_output(short, len(self.data.requests))

    def test_a_case_is_decided_only_on_evidence_available_at_its_cutoff(self):
        by_id = self.data.evidence_by_id()
        checked = 0
        for verdict, request in zip(self.verdicts, self.data.requests):
            cited = {s["evidence_id"] for s in verdict.steps if s["evidence_id"]}
            if not cited:
                continue
            for file_id in cited:
                with self.subTest(case=request.case_id, evidence=file_id):
                    self.assertLessEqual(by_id[file_id].captured_at, request.audit_at)
            checked += 1
            if checked >= 60:
                break
        self.assertGreater(checked, 0)

    def test_the_answer_does_not_depend_on_the_case_id(self):
        # Branching on a case id is forbidden, and this is how we show we do not.
        original = self.data.requests[5]
        renamed = replace(original, case_id="case_999999")
        self.assertEqual(self.auditor.audit(renamed).steps,
                         self.auditor.audit(original).steps)

    def test_the_answer_does_not_depend_on_the_workflow_claim(self):
        original = self.data.requests[7]
        for claim in ("COMPLETE", "PARTIALLY_COMPLETE", "NOT_STARTED"):
            with self.subTest(claim=claim):
                altered = replace(original, reported_status=claim)
                self.assertEqual(self.auditor.audit(altered).status,
                                 self.auditor.audit(original).status)

    def test_two_runs_of_the_same_case_agree(self):
        request = self.data.requests[11]
        self.assertEqual(self.auditor.audit(request).steps,
                         self.auditor.audit(request).steps)


if __name__ == "__main__":
    unittest.main()
