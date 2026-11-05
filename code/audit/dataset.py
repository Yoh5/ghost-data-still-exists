"""Loading the participant-facing dataset. Read-only, explicit UTF-8, no inference.

Only files under `dataset/` are read. Nothing here reaches outside it, which is how the
"participant-facing data only" rule is enforced in one place instead of being remembered
in many.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Row counts measured on the supplied dataset, asserted on load so a truncated or
# re-downloaded corpus fails loudly instead of quietly changing the answers.
EXPECTED_REQUESTS = 518
EXPECTED_CASE_RANGE = (33, 550)

csv.field_size_limit(10_000_000)


def repo_root() -> Path:
    """The repository root, resolved from this file so no user path is ever hardcoded."""
    return Path(__file__).resolve().parents[2]


def parse_time(value: str) -> datetime:
    """Parse the dataset's ISO-8601 Zulu timestamps into aware datetimes.

    Every comparison in this solution is between aware datetimes. A naive datetime
    compared with an aware one raises in Python, which is the behaviour we want: an
    unparsed timestamp must not silently sort as "earlier than everything".
    """
    v = value.strip()
    if not v:
        raise ValueError("empty timestamp")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    parsed = datetime.fromisoformat(v)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass(frozen=True, slots=True)
class Request:
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str          # a claim from the existing workflow; never evidence
    reported_at: datetime
    audit_at: datetime            # the cutoff: nothing captured later may be used
    request_text: str

    @property
    def case_number(self) -> int:
        """Numeric part of the case id.

        The input file is in numeric order, which is not lexicographic order
        (`case_100` sorts before `case_33`). Output rows are emitted in this order.
        """
        return int(self.case_id.split("_")[1])


@dataclass(frozen=True, slots=True)
class Identity:
    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One historical change to an identity field: the only route to old identifiers."""

    audit_id: str
    user_id: str
    event_time: datetime
    field_name: str
    old_value: str
    new_value: str


@dataclass(frozen=True, slots=True)
class Activity:
    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str          # also a claim
    details: str


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    data_category: str
    condition: str
    required_action: str


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    file_id: str
    file_path: str
    origin: str
    captured_at: datetime

    def resolve(self, dataset_dir: Path) -> Path:
        return dataset_dir / self.file_path

    @property
    def family(self) -> str:
        """databases | documents | images | logs | records."""
        return Path(self.file_path).parent.name


@dataclass(slots=True)
class Dataset:
    directory: Path
    requests: list[Request] = field(default_factory=list)
    identities: list[Identity] = field(default_factory=list)
    audit_log: list[AuditEntry] = field(default_factory=list)
    activity: list[Activity] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    evidence: list[EvidenceFile] = field(default_factory=list)

    def rule_for(self, data_category: str) -> list[Rule]:
        return [r for r in self.rules if r.data_category == data_category]

    def evidence_by_id(self) -> dict[str, EvidenceFile]:
        return {e.file_id: e for e in self.evidence}

    def evidence_available_at(self, moment: datetime) -> list[EvidenceFile]:
        """Evidence a case may legitimately use: captured at or before its `audit_at`.

        Filtering here, at the source, is what keeps the `audit_at` rule from being
        something each later stage has to remember.
        """
        return [e for e in self.evidence if e.captured_at <= moment]


def load(directory: Path | str | None = None, *, strict: bool = True) -> Dataset:
    """Load every participant-facing file.

    `strict` checks the shape we measured. A corpus that no longer matches is a reason to
    stop, not to carry on against different data than the one the solution was built for.
    """
    d = Path(directory) if directory else repo_root() / "dataset"
    if not d.is_dir():
        raise FileNotFoundError(f"dataset directory not found: {d}")

    data = Dataset(directory=d)

    for r in _rows(d / "deletion_requests.csv"):
        data.requests.append(Request(
            case_id=r["case_id"], email=r["email"],
            requested_at=parse_time(r["requested_at"]),
            reported_status=r["reported_status"],
            reported_at=parse_time(r["reported_at"]),
            audit_at=parse_time(r["audit_at"]),
            request_text=r["request_text"]))

    for r in _rows(d / "user_identities.csv"):
        data.identities.append(Identity(
            user_id=r["user_id"], name=r["name"], email=r["email"], phone=r["phone"],
            email_hash=r["email_hash"], updated_at=parse_time(r["updated_at"])))

    for r in _rows(d / "user_audit_log.csv"):
        data.audit_log.append(AuditEntry(
            audit_id=r["audit_id"], user_id=r["user_id"],
            event_time=parse_time(r["event_time"]), field_name=r["field_name"],
            old_value=r["old_value"], new_value=r["new_value"]))

    for r in _rows(d / "system_activity.csv"):
        data.activity.append(Activity(
            activity_id=r["activity_id"], event_time=parse_time(r["event_time"]),
            event_type=r["event_type"], source_system=r["source_system"],
            target_system=r["target_system"], resource_id=r["resource_id"],
            reported_result=r["reported_result"], details=r["details"]))

    for r in _rows(d / "deletion_rules.csv"):
        data.rules.append(Rule(rule_id=r["rule_id"], data_category=r["data_category"],
                               condition=r["condition"],
                               required_action=r["required_action"]))

    for r in _rows(d / "evidence_files.csv"):
        data.evidence.append(EvidenceFile(
            file_id=r["file_id"], file_path=r["file_path"], origin=r["origin"],
            captured_at=parse_time(r["captured_at"])))

    if strict:
        _check(data)
    return data


def load_samples(directory: Path | str | None = None) -> tuple[list[Request], dict[str, tuple[str, list[dict]]]]:
    """The 32 public requests and their correct answers: the labelled test set.

    Returns the requests, and `case_id -> (deletion_status, raw step dicts)`.
    """
    import json

    d = Path(directory) if directory else repo_root() / "dataset"
    requests = [Request(
        case_id=r["case_id"], email=r["email"], requested_at=parse_time(r["requested_at"]),
        reported_status=r["reported_status"], reported_at=parse_time(r["reported_at"]),
        audit_at=parse_time(r["audit_at"]), request_text=r["request_text"])
        for r in _rows(d / "sample_deletion_requests.csv")]

    gold: dict[str, tuple[str, list[dict]]] = {}
    for r in _rows(d / "sample_output.csv"):
        gold[r["case_id"]] = (r["deletion_status"], json.loads(r["steps_json"]))

    missing = [r.case_id for r in requests if r.case_id not in gold]
    if missing:
        raise ValueError(f"sample requests without an answer: {missing}")
    return requests, gold


def _check(data: Dataset) -> None:
    n = len(data.requests)
    if n != EXPECTED_REQUESTS:
        raise ValueError(f"expected {EXPECTED_REQUESTS} requests, found {n}")

    numbers = [r.case_number for r in data.requests]
    if (min(numbers), max(numbers)) != EXPECTED_CASE_RANGE:
        raise ValueError(f"case id range moved: {min(numbers)}..{max(numbers)}")
    if len({r.case_id for r in data.requests}) != n:
        raise ValueError("duplicate case_id in deletion_requests.csv")
    if numbers != sorted(numbers):
        raise ValueError("deletion_requests.csv is no longer in numeric case order")

    if len({i.user_id for i in data.identities}) != len(data.identities):
        raise ValueError("duplicate user_id in user_identities.csv")

    missing = [e.file_id for e in data.evidence if not e.resolve(data.directory).is_file()]
    if missing:
        raise ValueError(f"evidence files listed in the manifest but absent: {missing}")
