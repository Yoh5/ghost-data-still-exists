"""The step vocabulary, and the ordering that the specification fixes.

Measurement M1 (PLAN.md): across all 32 sample cases, the published step order is exactly

    (phase, operation order in the spec table, system_id, resource_id)   ascending

so ordering and numbering are mechanical. They are computed here, once, and never
decided by a model. That removes a whole class of error from the output.

A second reduction follows from the spec's own table: `phase` and `state` are both
functions of `operation`. There is no operation that can carry two states. So a step is
really a triple (operation, system_id, resource_id) plus the evidence that proves it, and
the four redundant fields are derived on serialisation rather than carried around and
risked.
"""
from __future__ import annotations

from dataclasses import dataclass

FINDING = "FINDING"
REMEDIATION = "REMEDIATION"
VERIFICATION = "VERIFICATION"

PHASE_ORDER = (FINDING, REMEDIATION, VERIFICATION)

# operation -> (phase, state), in the exact order of the table in problem_statement.md.
# The order of this mapping is the tie-break inside a phase, so it must not be sorted.
OPERATIONS: dict[str, tuple[str, str]] = {
    "REPORT_REMAINING_RECORD":   (FINDING, "PRESENT"),
    "REPORT_EXPOSED_PII":        (FINDING, "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW":   (FINDING, "ACTIVE"),
    "REPORT_RESTORE_RISK":       (FINDING, "ACTIVE"),
    "DISABLE_DATA_FLOW":         (REMEDIATION, "DISABLED"),
    "BLOCK_RESTORE":             (REMEDIATION, "BLOCKED"),
    "DELETE_RECORD":             (REMEDIATION, "ABSENT"),
    "REDACT_RECORD":             (REMEDIATION, "REDACTED"),
    "ANONYMIZE_RECORD":          (REMEDIATION, "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT":      (VERIFICATION, "ABSENT"),
    "VERIFY_RECORD_PRESENT":     (VERIFICATION, "PRESENT"),
    "VERIFY_RECORD_REDACTED":    (VERIFICATION, "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED":  (VERIFICATION, "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": (VERIFICATION, "DISABLED"),
    "VERIFY_RESTORE_BLOCKED":    (VERIFICATION, "BLOCKED"),
}

OPERATION_RANK = {op: i for i, op in enumerate(OPERATIONS)}
PHASE_RANK = {p: i for i, p in enumerate(PHASE_ORDER)}

FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")

# The verification that proves each remediation actually landed, and the verification that
# proves an already-compliant resource is in its required state. Same mapping both ways:
# the required end state is what gets verified, whether or not we had to act to reach it.
VERIFY_FOR_STATE = {
    "ABSENT":     "VERIFY_RECORD_ABSENT",
    "PRESENT":    "VERIFY_RECORD_PRESENT",
    "REDACTED":   "VERIFY_RECORD_REDACTED",
    "ANONYMIZED": "VERIFY_RECORD_ANONYMIZED",
    "DISABLED":   "VERIFY_DATA_FLOW_DISABLED",
    "BLOCKED":    "VERIFY_RESTORE_BLOCKED",
}


class StepError(ValueError):
    """A step that cannot be serialised. Raised, never silently repaired."""


@dataclass(frozen=True, slots=True)
class Step:
    """One step, before numbering.

    `evidence_id` is the participant-visible file_id / activity_id / audit_id that proves
    the step. Proposed remediation and future verification for an INCOMPLETE case carry an
    empty string, as the spec requires. An empty string is a deliberate statement that the
    step describes future work; it is not a missing value, and nothing fills it in later.
    """

    operation: str
    system_id: str
    resource_id: str
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise StepError(f"unknown operation {self.operation!r}; "
                            "the spec allows no others")
        for name in ("system_id", "resource_id"):
            if not getattr(self, name):
                raise StepError(f"{name} is empty on {self.operation}")

    @property
    def phase(self) -> str:
        return OPERATIONS[self.operation][0]

    @property
    def state(self) -> str:
        return OPERATIONS[self.operation][1]

    @property
    def sort_key(self) -> tuple[int, int, str, str]:
        return (PHASE_RANK[self.phase], OPERATION_RANK[self.operation],
                self.system_id, self.resource_id)


def order_steps(steps: list[Step]) -> list[Step]:
    """Put steps in the order the spec fixes. Stable, so equal keys keep input order."""
    return sorted(steps, key=lambda s: s.sort_key)


def serialise(steps: list[Step]) -> list[dict]:
    """Order, number from 1, and expand to the seven required fields.

    Duplicate (operation, system_id, resource_id) triples are an upstream bug: the same
    step twice would shift every following step_no. We refuse rather than emit it.
    """
    ordered = order_steps(steps)
    seen: set[tuple[str, str, str]] = set()
    for s in ordered:
        key = (s.operation, s.system_id, s.resource_id)
        if key in seen:
            raise StepError(f"duplicate step {key}")
        seen.add(key)
    return [
        {"step_no": i, "phase": s.phase, "system_id": s.system_id,
         "resource_id": s.resource_id, "operation": s.operation, "state": s.state,
         "evidence_id": s.evidence_id}
        for i, s in enumerate(ordered, 1)
    ]


def parse(raw: list[dict]) -> list[Step]:
    """Read a published step array back into Steps, for scoring against the samples."""
    return [Step(operation=d["operation"], system_id=d["system_id"],
                 resource_id=d["resource_id"], evidence_id=d.get("evidence_id", ""))
            for d in raw]
