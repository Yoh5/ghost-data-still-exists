"""Reading evidence, and deciding what it means.

The division under test is the one the design rests on: a reader reports what a file
says, a policy decides whether that is acceptable. Each half is checked on its own, so a
parser bug cannot be hidden by a lenient rule, or a rule bug by a generous parser.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit import dataset, evidence, inventory, policy  # noqa: E402

WHEN = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def observation(**kwargs) -> evidence.Observation:
    base = dict(file_id="evidence_x", captured_at=WHEN, resource_id="account_1",
                system_id="account_service")
    base.update(kwargs)
    return evidence.Observation(**base)


def candidate(obs: evidence.Observation, via: str = "evidence") -> inventory.Candidate:
    cand = inventory.Candidate(resource_id=obs.resource_id, system_id=obs.system_id,
                               via=via)
    cand.observations = [obs]
    return cand


class Tokeniser(unittest.TestCase):
    def test_bare_quoted_and_mixed_pairs_are_all_read(self):
        kv = evidence.kv_pairs('a=1 b="two words" c=three level=INFO')
        self.assertEqual(kv["a"], "1")
        self.assertEqual(kv["b"], "two words")
        self.assertEqual(kv["c"], "three")

    def test_pipe_and_syslog_shapes_are_read_by_the_same_tokeniser(self):
        pipe = evidence.kv_pairs('2026-01-01T00:00:00Z | DEBUG | search_service | '
                                 'tr-1 | index_query_completed | resource_id="search_7"')
        self.assertEqual(pipe["resource_id"], "search_7")
        syslog = evidence.kv_pairs('<15>1 node-1 account_service tr-2 - - '
                                   'resource_id="account_8" rows="0"')
        self.assertEqual(syslog["resource_id"], "account_8")
        self.assertEqual(syslog["rows"], "0")

    def test_a_json_log_line_is_read_as_fields_not_as_text(self):
        """Two formats write a JSON object, where a key=value regex finds nothing.

        The resource id and trace id have their own patterns, so such a line LOOKED
        read while every field saying whose record it is was dropped in silence. That
        is the worst shape of parser bug: it leaves no trace of having failed.
        """
        line = ('2026-09-16T08:52:49Z {"severity":"DEBUG","logger":"security_service",'
                '"trace_id":"tr-9028396","event":"audit_record_query_started",'
                '"subject_ref":"user_61","attempt":"1"}')
        kv = evidence.kv_pairs(line)
        self.assertEqual(kv["subject_ref"], "user_61")
        self.assertEqual(kv["event"], "audit_record_query_started")
        self.assertEqual(kv["logger"], "security_service")

    def test_a_malformed_json_line_degrades_instead_of_raising(self):
        kv = evidence.kv_pairs('2026-01-01T00:00:00Z {"broken": ')
        self.assertIsInstance(kv, dict)

    def test_the_escaped_json_in_a_message_variant_still_works(self):
        line = ('2026-09-30T11:51:03Z requestId=tr-2263120 level=DEBUG '
                'function=profile_service message="resource_id=\\"account_66777\\" '
                'rows=\\"1\\""')
        kv = evidence.kv_pairs(line)
        self.assertEqual(kv.get("resource_id"), "account_66777")

    def test_the_system_that_owns_a_resource_comes_from_its_prefix(self):
        self.assertEqual(evidence.system_for("audit_record_12"), "security_service")
        self.assertEqual(evidence.system_for("data_flow_3"), "integration_service")
        self.assertIsNone(evidence.system_for("mystery_9"))


class WhatAnObservationMayTestifyTo(unittest.TestCase):
    def test_a_plain_log_line_cannot_establish_redaction(self):
        obs = observation(reader="log", present=True, category="SUPPORT_MESSAGE",
                          resource_id="support_1", system_id="support_platform")
        self.assertFalse(obs.field_level)
        state, _ = policy.observed_state(candidate(obs), "SUPPORT_MESSAGE")
        self.assertEqual(state, policy.PRESENT)

    def test_a_readback_that_lists_fields_can(self):
        obs = observation(reader="log", present=True, enumerated=True,
                          category="SUPPORT_MESSAGE", resource_id="support_1",
                          system_id="support_platform")
        self.assertTrue(obs.field_level)
        state, _ = policy.observed_state(candidate(obs), "SUPPORT_MESSAGE")
        self.assertEqual(state, policy.REDACTED)

    def test_a_record_that_still_carries_an_identifier_is_exposed(self):
        obs = observation(reader="snapshot_bundle", present=True,
                          resource_id="tombstone_1", system_id="identity_service")
        obs.add_pii("email", "someone@example.com")
        state, _ = policy.observed_state(candidate(obs), "ACCOUNT_TOMBSTONE")
        self.assertEqual(state, policy.PRESENT)

    def test_null_in_any_spelling_stores_nothing(self):
        obs = observation()
        for value in (None, "null", "NULL", "", "   ", "redacted"):
            obs.add_pii("email", value)
        self.assertEqual(obs.pii, {})

    def test_a_placeholder_is_never_indexed_as_an_identifier(self):
        """`no direct identifier` is prose, not a person.

        Indexing it would tie every anonymised record in the corpus to the same
        imaginary subject -- and then hand them all to whichever case asked first.
        """
        obs = observation()
        obs.add_subject("null", "NONE", "no direct identifier", "n/a", "-", "unknown",
                        "", None)
        self.assertEqual(obs.subject_keys, set())

    def test_a_real_identifier_still_is_indexed(self):
        obs = observation()
        obs.add_subject("someone@example.com", "user_42")
        self.assertEqual(obs.subject_keys, {"someone@example.com", "user_42"})

    def test_no_placeholder_reaches_the_real_index(self):
        # The same guarantee over the whole corpus rather than one constructed record.
        from audit.evidence import NOT_IDENTIFIERS
        indexed = set()
        for obs in TheCorpusAsRead.reader.observations:
            indexed |= obs.subject_keys
        self.assertEqual(indexed & NOT_IDENTIFIERS, set())

    def test_a_tri_state_unknown_never_becomes_absent(self):
        obs = observation(reader="log", present=None)
        state, _ = policy.observed_state(candidate(obs), "USER_PROFILE")
        self.assertEqual(state, policy.UNKNOWN)
        self.assertNotEqual(state, policy.ABSENT)

    def test_a_candidate_with_no_observation_is_unknown(self):
        empty = inventory.Candidate(resource_id="account_1",
                                    system_id="account_service", via="burst")
        state, proof = policy.observed_state(empty, "USER_PROFILE")
        self.assertEqual(state, policy.UNKNOWN)
        self.assertIsNone(proof)

    def test_a_process_is_read_from_its_switch_not_from_its_existence(self):
        obs = observation(reader="log", present=None, resource_id="data_flow_1",
                          system_id="integration_service")
        obs.flags["enabled"] = "true"
        state, _ = policy.observed_state(candidate(obs), "DATA_FLOW")
        self.assertEqual(state, policy.ACTIVE)

    def test_a_backup_is_read_from_whether_restore_is_allowed(self):
        obs = observation(reader="service_export", present=True,
                          resource_id="backup_1", system_id="backup_service")
        obs.flags["restore_allowed"] = "false"
        state, _ = policy.observed_state(candidate(obs), "BACKUP_ARCHIVE")
        self.assertEqual(state, policy.BLOCKED)

    def test_active_is_not_a_state_a_stored_record_can_be_in(self):
        # `account_status=ACTIVE` means the profile exists, not that a process runs.
        obs = observation(reader="sqlite:customer_profiles", present=True,
                          declared_state="ACTIVE")
        obs.add_pii("email", "someone@example.com")
        state, _ = policy.observed_state(candidate(obs), "USER_PROFILE")
        self.assertEqual(state, policy.PRESENT)

    def test_a_tombstone_marked_deleted_is_still_a_row_that_exists(self):
        obs = observation(reader="snapshot_bundle", present=True,
                          resource_id="tombstone_1", system_id="identity_service")
        obs.flags["account_status"] = "DELETED"
        obs.add_pii("email", "someone@example.com")
        state, _ = policy.observed_state(candidate(obs), "ACCOUNT_TOMBSTONE")
        self.assertEqual(state, policy.PRESENT)


class CategoryResolution(unittest.TestCase):
    """Who gets to say what kind of record this is."""

    def _obs(self, reader, category):
        return observation(reader=reader, present=True, category=category,
                           resource_id="backup_9287", system_id="backup_service")

    def test_a_screenshot_cannot_move_a_record_out_of_its_family(self):
        """A vision misread once flipped a backup from "block" to "delete".

        The treatment of a record must not depend on the least reliable source in the
        corpus. Two runs of identical code produced different plans for backup_9287
        because a screenshot's category overrode the deterministic prefix.
        """
        cand = inventory.Candidate(resource_id="backup_9287",
                                   system_id="backup_service", via="evidence")
        wrong = self._obs("vision", "USER_PROFILE")
        cand.observations = [wrong]
        self.assertEqual(policy.category_of(cand, wrong), "BACKUP_ARCHIVE")

    def test_a_screenshot_may_still_refine_within_the_family(self):
        cand = inventory.Candidate(resource_id="support_1",
                                   system_id="support_platform", via="evidence")
        refined = observation(reader="vision", present=True,
                              category="SUPPORT_ATTACHMENT",
                              resource_id="support_1", system_id="support_platform")
        cand.observations = [refined]
        self.assertEqual(policy.category_of(cand, refined), "SUPPORT_ATTACHMENT")

    def test_a_text_reader_is_still_trusted_to_recategorise(self):
        # The handover file legitimately says a support record is an attachment.
        cand = inventory.Candidate(resource_id="backup_9287",
                                   system_id="backup_service", via="evidence")
        stated = self._obs("handover", "LEGAL_HOLD_RECORD")
        cand.observations = [stated]
        self.assertEqual(policy.category_of(cand, stated), "LEGAL_HOLD_RECORD")

    def test_an_unknown_category_falls_back_to_the_prefix(self):
        cand = inventory.Candidate(resource_id="search_7", system_id="search_service",
                                   via="evidence")
        vague = observation(reader="log", present=True, category="something_else",
                            resource_id="search_7", system_id="search_service")
        cand.observations = [vague]
        self.assertEqual(policy.category_of(cand, vague), "SEARCH_INDEX_ENTRY")


class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = dataset.load()
        cls.policy = policy.Policy(cls.data)

    def test_each_supplied_rule_maps_to_an_end_state(self):
        for rule in self.data.rules:
            with self.subTest(rule=rule.rule_id):
                self.assertIn(rule.required_action, policy.STATE_BY_ACTION)

    def test_the_two_support_rules_pull_in_opposite_directions(self):
        self.assertEqual(self.policy.required_state("SUPPORT_MESSAGE"), policy.REDACTED)
        self.assertEqual(self.policy.required_state("SUPPORT_ATTACHMENT"), policy.ABSENT)

    def test_retained_categories_must_remain_present(self):
        for category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
            self.assertEqual(self.policy.required_state(category), policy.PRESENT)

    def test_a_category_no_rule_covers_is_unknown_not_deleted(self):
        # Deleting a record nobody asked us to delete is the other half of the failure.
        self.assertEqual(self.policy.required_state("SOMETHING_NEW"), policy.UNKNOWN)

    def test_the_run_states_the_treatment_the_rules_cannot_infer(self):
        cand = inventory.Candidate(resource_id="support_1",
                                   system_id="support_platform", via="evidence")
        cand.activities = [dataset.Activity(
            activity_id="activity_1", event_time=WHEN, event_type="DELETE_RECORD",
            source_system="deletion_worker", target_system="support_platform",
            resource_id="support_1", reported_result="FAILED", details="")]
        self.assertEqual(policy.required_from_activity(cand), policy.ABSENT)

    def test_only_a_policy_actor_may_speak_for_policy(self):
        cand = inventory.Candidate(resource_id="search_1", system_id="search_service",
                                   via="evidence")
        cand.activities = [dataset.Activity(
            activity_id="activity_2", event_time=WHEN, event_type="DELETE_RECORD",
            source_system="search_indexer", target_system="search_service",
            resource_id="search_1", reported_result="SUCCESS", details="")]
        self.assertEqual(policy.required_from_activity(cand), policy.UNKNOWN)

    def test_the_latest_policy_action_wins(self):
        cand = inventory.Candidate(resource_id="support_1",
                                   system_id="support_platform", via="evidence")
        cand.activities = [
            dataset.Activity("activity_1", WHEN - timedelta(hours=2), "REDACT_RECORD",
                             "deletion_worker", "support_platform", "support_1",
                             "SUCCESS", ""),
            dataset.Activity("activity_2", WHEN, "DELETE_RECORD", "deletion_worker",
                             "support_platform", "support_1", "SUCCESS", ""),
        ]
        self.assertEqual(policy.required_from_activity(cand), policy.ABSENT)


class TheCorpusAsRead(unittest.TestCase):
    """Integration: the real files, read once, checked for the properties we rely on."""

    @classmethod
    def setUpClass(cls):
        cls.data = dataset.load()
        cls.reader = evidence.EvidenceReader(cls.data)
        cls.reader.read_all()

    def test_every_evidence_file_is_accounted_for_one_way_or_another(self):
        seen = {o.file_id for o in self.reader.observations}
        seen |= {f for f, _ in self.reader.unread}
        seen |= {f for f, _ in self.reader.accounted}
        self.assertEqual(seen, {e.file_id for e in self.data.evidence})

    def test_an_unreadable_file_is_never_filed_as_merely_empty(self):
        # The two lists mean different things and must not overlap: "could not read"
        # is a problem, "read and empty" is a fact.
        self.assertEqual({f for f, _ in self.reader.unread}
                         & {f for f, _ in self.reader.accounted}, set())

    def test_nothing_contributes_nothing_in_silence(self):
        """Every file either yields observations, or coverage, or a precise reason.

        The vaguer version of this test ("only screenshots are unread") caught three
        real problems: screenshots filed under a reason that overwrote the real one, an
        empty SQL inventory whose coverage was registered without a system and so could
        prove nothing, and two PDFs that name a person but no auditable record. A file
        that silently does nothing is indistinguishable from a reader that silently
        fails.
        """
        with_observations = {o.file_id for o in self.reader.observations}
        with_coverage = {c.file_id for c in self.reader.coverage}
        explained = dict(self.reader.unread) | dict(self.reader.accounted)
        for ev in self.data.evidence:
            with self.subTest(file=ev.file_id, path=Path(ev.file_path).name):
                if ev.file_id in with_observations or ev.file_id in with_coverage:
                    continue
                self.assertIn(ev.file_id, explained)
                self.assertNotEqual(explained[ev.file_id], "no observation extracted")

    def test_screenshots_are_named_as_needing_a_model(self):
        images = {e.file_id for e in self.data.evidence if e.family == "images"}
        for file_id, why in self.reader.unread:
            if file_id in images:
                self.assertIn("multimodal", why)

    def test_an_empty_enumeration_still_proves_absence(self):
        # customer_data_inventory_20260905.sql creates every table and inserts nothing.
        empty = [c for c in self.reader.coverage
                 if c.file_id == "evidence_90" and not c.resource_ids]
        self.assertTrue(empty)
        for cov in empty:
            with self.subTest(category=cov.category):
                self.assertTrue(cov.system_id, "coverage without a system proves nothing")

    def test_a_pii_scan_settles_ownership_and_exposure_at_once(self):
        """`matched_value` on a scan line is the platform reporting an exposure.

            WARN ... resource_id=support_9553 event=message_pii_scan
                 matched_value="e.varga90@yahoo.com" detector=direct_identifier

        It tells us whose record it is AND that the record still holds an identifier.
        It must not count as a field enumeration: a scan reports what it matched, never
        the whole record, so it can show an identifier is present and never that the
        others are gone.
        """
        found = [o for o in self.reader.observations
                 if o.resource_id == "support_9553"
                 and "pii" in o.flags.get("event", "")]
        self.assertTrue(found, "the scan line produced no observation")
        scan = found[0]
        self.assertIs(scan.present, True)
        self.assertIn("e.varga90@yahoo.com", scan.subject_keys)
        self.assertTrue(scan.exposes_pii)
        self.assertFalse(scan.enumerated,
                         "a scan must not be allowed to prove redaction")

    def test_a_scan_never_claims_the_record_was_redacted(self):
        for obs in self.reader.observations:
            if "pii" in obs.flags.get("event", "") and obs.reader == "log":
                with self.subTest(resource=obs.resource_id):
                    self.assertFalse(obs.field_level)

    def test_the_shift_handover_grounds_the_case_it_is_cited_for(self):
        # sample case_11 cites evidence_03 for account_4248.
        rows = [o for o in self.reader.observations
                if o.file_id == "evidence_03" and o.resource_id == "account_4248"]
        self.assertTrue(rows)
        self.assertIs(rows[0].present, False)
        self.assertIn("novak.tomasz@icloud.com", rows[0].subject_keys)

    def test_the_cutoff_is_applied_at_the_query(self):
        early = self.data.evidence[0].captured_at - timedelta(days=3650)
        self.assertEqual(self.reader.for_identifiers({"anything"}, not_after=early), [])

    def test_absence_is_only_claimed_from_an_enumeration(self):
        proof = self.reader.proof_of_absence(
            "account_service", {"nobody@example.invalid"},
            not_after=datetime(2030, 1, 1, tzinfo=timezone.utc))
        self.assertIsNotNone(proof)
        self.assertNotIn(proof.file_id, {f for f, _ in self.reader.unread})

    def test_a_subject_never_holds_two_resources_in_one_system(self):
        """Measured on the published answers: 111 of 111 resources, one per system.

        A person has one profile, one search entry, one analytics record. Several
        candidates in one system is the shape the deletion run's leads arrive in, so
        this is the constraint that keeps attribution honest rather than generous.
        """
        from audit import identity as identity_module
        index = identity_module.IdentityIndex(self.data)
        inv = inventory.Inventory(self.data, self.reader)
        for request in self.data.requests[:40]:
            subject = index.resolve(request.email)
            found = inv.resources_for(subject, request.audit_at)
            systems = [c.system_id for c in found.values()]
            with self.subTest(case=request.case_id):
                self.assertEqual(len(systems), len(set(systems)),
                                 f"two resources in one system: "
                                 f"{sorted((c.system_id, r) for r, c in found.items())}")

    def test_turning_the_constraint_off_is_what_produces_duplicates(self):
        # Shows the test above is measuring the rule and not an accident of the data.
        from audit import identity as identity_module
        index = identity_module.IdentityIndex(self.data)
        loose = inventory.Inventory(self.data, self.reader, one_per_system=False)
        duplicated = 0
        for request in self.data.requests[:40]:
            subject = index.resolve(request.email)
            systems = [c.system_id
                       for c in loose.resources_for(subject, request.audit_at).values()]
            duplicated += len(systems) != len(set(systems))
        self.assertGreater(duplicated, 0,
                           "without the rule there should be cases with duplicates")

    def test_a_subject_present_in_an_enumeration_is_not_proven_absent(self):
        covering = next(c for c in self.reader.coverage if c.subject_keys)
        key = sorted(covering.subject_keys)[0]
        proof = self.reader.proof_of_absence(
            covering.system_id, {key}, not_after=covering.captured_at,
            category=covering.category)
        self.assertIsNone(proof)


if __name__ == "__main__":
    unittest.main()
