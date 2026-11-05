"""The decision: required state versus observed state, and the gap between them.

One engine, not two. `COMPLETE` is not a separate code path -- it is the case whose gap
set is empty. That is not a stylistic preference: measured on the published answers, 21 of
22 `INCOMPLETE` cases carry verification steps for resources that needed no remediation,
so the verification block of an incomplete case has the same shape as a complete one's.
Two code paths would have had to agree with each other, and would eventually not.

The fail-closed rule lives here. A resource whose state could not be established does not
become compliant by default. If it was tied to the subject by evidence, it blocks the
`COMPLETE` verdict, because an unaudited copy reported as deleted is precisely the failure
in the problem statement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .dataset import Dataset, Request
from .evidence import EvidenceReader
from .identity import IdentityError, IdentityIndex
from .inventory import Candidate, Inventory
from .policy import (ABSENT, ACTIVE, ANONYMIZED, BLOCKED, DISABLED, PRESENT, REDACTED,
                     UNKNOWN, Policy, category_of, observed_state,
                     required_from_activity)
from .steps import VERIFY_FOR_STATE, Step, serialise

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
NOT_APPLICABLE = "NOT_APPLICABLE"

#: (required state, observed state) -> (finding operation, remediation operation).
#: Every pair that is a gap is listed; anything absent from this table is either
#: compliant or unknown, and neither produces a finding.
GAP_OPERATIONS: dict[tuple[str, str], tuple[str, str]] = {
    (ABSENT, PRESENT):      ("REPORT_REMAINING_RECORD", "DELETE_RECORD"),
    (ABSENT, REDACTED):     ("REPORT_REMAINING_RECORD", "DELETE_RECORD"),
    (ABSENT, ANONYMIZED):   ("REPORT_REMAINING_RECORD", "DELETE_RECORD"),
    (REDACTED, PRESENT):    ("REPORT_EXPOSED_PII", "REDACT_RECORD"),
    (ANONYMIZED, PRESENT):  ("REPORT_EXPOSED_PII", "ANONYMIZE_RECORD"),
    (DISABLED, ACTIVE):     ("REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW"),
    (BLOCKED, ACTIVE):      ("REPORT_RESTORE_RISK", "BLOCK_RESTORE"),
}

#: Required states for which an ABSENT record means there is simply nothing to act on,
#: rather than a violation. A data flow that no longer exists cannot recreate anything.
ABSENT_IS_MOOT = {REDACTED, ANONYMIZED, DISABLED, BLOCKED}


@dataclass(slots=True)
class Verdict:
    case_id: str
    status: str
    steps: list[dict] = field(default_factory=list)
    #: Everything the engine could not settle, kept for the evaluation report. These are
    #: not warnings to be tidied away; they are the measured edge of what we can prove.
    notes: list[str] = field(default_factory=list)

    @property
    def steps_json(self) -> str:
        import json
        return json.dumps(self.steps, ensure_ascii=False, separators=(",", ":"))


class Auditor:
    def __init__(self, data: Dataset, index: IdentityIndex, reader: EvidenceReader,
                 inventory: Inventory, policy: Policy, *,
                 authorizes_deletion: Callable[[Request], bool] | None = None,
                 policy_source: str = "prefer-activity") -> None:
        self.data = data
        self.index = index
        self.reader = reader
        self.inventory = inventory
        self.policy = policy
        #: "rules-first" takes the treatment from deletion_rules.csv and consults the
        #: deletion run only when no rule covers the category; "prefer-activity" takes
        #: the run's own policy determination when it made one. Swept in
        #: code/evaluation/sweep_attribution.py.
        self.policy_source = policy_source
        #: Intent classification is injected, not hardcoded, so the rule-free baseline
        #: and the model-backed classifier are scored through the same engine.
        self.authorizes_deletion = authorizes_deletion or (lambda _r: True)

    def audit(self, request: Request) -> Verdict:
        if not self.authorizes_deletion(request):
            # No deletion was requested, so no deletion or deletion verification is
            # authorised. Producing checks here would mean auditing someone who asked
            # us not to touch their account.
            return Verdict(request.case_id, NOT_APPLICABLE, [])

        try:
            subject = self.index.resolve(request.email)
        except IdentityError as why:
            # We cannot say whose data to look for. Reporting COMPLETE here would be the
            # ghost: "we found nothing, so there is nothing".
            return Verdict(request.case_id, INCOMPLETE, [],
                           notes=[f"identity unresolved: {why}"])

        candidates = self.inventory.resources_for(subject, request.audit_at)

        findings: list[Step] = []
        remediation: list[Step] = []
        verification: list[Step] = []
        notes: list[str] = []
        blocked = False

        for resource_id in sorted(candidates):
            cand = candidates[resource_id]
            observation = cand.latest_observation()
            category = category_of(cand, observation)
            if not category:
                notes.append(f"{resource_id}: no data category")
                continue

            required = self.policy.required_state(category)
            attempted = required_from_activity(cand)
            if self.policy_source == "prefer-activity" and attempted != UNKNOWN:
                required = attempted
            elif required == UNKNOWN:
                required = attempted
            if required == UNKNOWN:
                notes.append(f"{resource_id}: no rule covers {category}")
                continue

            observed, proof = observed_state(cand, category)

            # Absence is not the absence of evidence. It has to be shown by a file that
            # enumerates the system and does not contain the subject.
            #
            # A lead reached by following the subject's own deletion run is tied to them
            # by that run, so it qualifies too. What does not qualify is a resource with
            # no tie at all: an enumeration that does not contain the subject says
            # nothing about whether such a record was ever theirs, and allowing it would
            # "prove absent" every stranger's record a run happened to touch.
            if observed == UNKNOWN and required == ABSENT and cand.via:
                cover = self.reader.proof_of_absence(
                    cand.system_id, subject.identifiers,
                    not_after=request.audit_at, category=category)
                if cover is not None:
                    observed = ABSENT
                    proof = None
                    cand.absence_proof = cover.file_id

            if observed == UNKNOWN and category == "BACKUP_ARCHIVE":
                # A restore path whose status nobody established is a restore path. The
                # completion criterion is "no active sync, import or restore path can
                # recreate the data", and an unknown does not satisfy it. This is the
                # one place where fail-closed means asserting a risk rather than
                # withholding a verdict, because here the two are the same thing: an
                # archive that might be restorable has to be blocked either way.
                observed = ACTIVE

            if observed == UNKNOWN:
                if cand.grounded and cand.observations and required != PRESENT:
                    # Evidence ties this resource to the subject but does not settle its
                    # state, and policy requires us to have *changed* it. An unverified
                    # copy that should have been removed, redacted, anonymised, disabled
                    # or blocked may still expose the person, so the deletion is not
                    # provably complete.
                    blocked = True
                    notes.append(f"{resource_id}: state not established ({category})")
                elif cand.grounded:
                    # Required state is PRESENT: a retained record. Not being able to
                    # confirm it is a gap in our proof of *retention*, not evidence that
                    # prohibited data survives, so it does not by itself overturn the
                    # verdict. Measured: blocking here turned two correct COMPLETE
                    # verdicts into INCOMPLETE and moved no other case.
                    notes.append(f"{resource_id}: retention not confirmed ({category})")
                    # A verification step is a check to RUN, not a claim about the state
                    # now. Policy says this record must still be there afterwards, so the
                    # check belongs in the plan even though we could not confirm it at the
                    # cutoff. It carries no citation, which is what the spec requires of
                    # future work -- and in a COMPLETE case, where every verification must
                    # cite its proof, it is dropped rather than published uncited.
                    verification.append(Step(VERIFY_FOR_STATE[required],
                                             cand.system_id, resource_id))
                continue

            if observed == ABSENT and required in ABSENT_IS_MOOT:
                continue

            evidence_id = cand.absence_proof or (proof.file_id if proof else "")

            gap = GAP_OPERATIONS.get((required, observed))
            if gap:
                finding_op, remediation_op = gap
                findings.append(Step(finding_op, cand.system_id, resource_id,
                                     evidence_id))
                remediation.append(Step(remediation_op, cand.system_id, resource_id))
            elif required == PRESENT and observed == ABSENT:
                # A record policy requires us to keep has gone. No allowed operation
                # restores it, so it cannot be remediated -- but the deletion is not
                # complete either, and saying so is the point.
                blocked = True
                notes.append(f"{resource_id}: policy-required record is missing")

            verification.append(Step(VERIFY_FOR_STATE[required], cand.system_id,
                                     resource_id, evidence_id))

        status = INCOMPLETE if (findings or blocked) else COMPLETE

        if status == COMPLETE:
            # Verification of a complete case must cite the evidence that proves the
            # state. A check we cannot point at is not a proof, so it is dropped rather
            # than published with an empty citation.
            kept = [s for s in verification if s.evidence_id]
            dropped = len(verification) - len(kept)
            if dropped:
                notes.append(f"{dropped} verification step(s) without evidence dropped")
            steps = serialise(kept)
        else:
            # Proposed remediation and future verification describe work not yet done,
            # so the spec requires an empty evidence_id on both.
            future = [Step(s.operation, s.system_id, s.resource_id)
                      for s in verification]
            steps = serialise(findings + remediation + future)

        return Verdict(request.case_id, status, steps, notes)
