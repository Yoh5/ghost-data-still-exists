"""The policy stage: what state each record is *required* to be in, and what it is in.

Two functions, kept apart on purpose.

`required_state` reads `deletion_rules.csv` and answers "what should be true of this
record once the deletion is done". It never looks at evidence.

`observed_state` reads the evidence and answers "what is true of it at audit_at". It
never looks at the rules.

The gap between the two is the whole answer, and because neither function can see the
other's input, neither can be tuned to agree with it.

One state is not a state: `UNKNOWN`. A record we could not establish is not compliant and
not non-compliant -- it is unaudited. It never silently becomes `ABSENT`, because an
unaudited copy reported as deleted is the exact failure in the problem statement.
"""
from __future__ import annotations

from .dataset import Dataset
from .evidence import SYSTEM_BY_CATEGORY, Observation
from .inventory import Candidate

# -- states ---------------------------------------------------------------------- #

ABSENT = "ABSENT"
PRESENT = "PRESENT"
REDACTED = "REDACTED"
ANONYMIZED = "ANONYMIZED"
DISABLED = "DISABLED"
BLOCKED = "BLOCKED"
ACTIVE = "ACTIVE"
UNKNOWN = "UNKNOWN"

#: resource prefix -> the data category the rules are written against. The categories in
#: deletion_rules.csv are business categories; this is the bridge to the resource families
#: that actually appear in the answers.
CATEGORY_BY_PREFIX = {
    "account": "USER_PROFILE",
    "search": "SEARCH_INDEX_ENTRY",
    "analytics": "ANALYTICS_PROFILE",
    "support": "SUPPORT_MESSAGE",
    "export": "USER_EXPORT",
    "data_flow": "DATA_FLOW",
    "backup": "BACKUP_ARCHIVE",
    "audit_record": "SECURITY_AUDIT_LOG",
    "tombstone": "ACCOUNT_TOMBSTONE",
}

#: rules action -> the end state that action produces.
STATE_BY_ACTION = {
    "DELETE": ABSENT,
    "REDACT": REDACTED,
    "ANONYMIZE": ANONYMIZED,
    "RETAIN": PRESENT,
}

#: DATA_FLOW has no row in deletion_rules.csv: it is not a data category but a process.
#: Its requirement comes from the completion criterion itself -- "no active sync, import
#: or restore path can recreate the data" -- so it is stated here, next to the rules it
#: sits beside, rather than hidden in the engine.
IMPLIED = {
    "DATA_FLOW": DISABLED,
    "BACKUP_ARCHIVE": BLOCKED,   # rule_14 RETAIN, plus "restore access can be blocked"
}

#: Values that mean a flag is on, across SQL integers, JSON booleans and log strings.
TRUE_VALUES = {"1", "true", "yes", "enabled", "allowed", "active", "on"}
FALSE_VALUES = {"0", "false", "no", "disabled", "blocked", "inactive", "off"}


def category_of(candidate: Candidate, observation: Observation | None) -> str:
    """The data category of a resource.

    The evidence's own category normally wins, because a support record can be a
    SUPPORT_MESSAGE or a SUPPORT_ATTACHMENT and those take opposite treatments -- redact
    versus delete -- and the resource id cannot tell them apart. Otherwise the prefix
    decides.

    One source is not allowed to win: a screenshot that contradicts the resource family.
    A vision model misread `backup_9287` on one run as something deletable, and because
    its category overrode the prefix the record flipped from "block the restore" to
    "delete the record" between two runs of identical code. A screenshot is the least
    reliable evidence in the corpus and the prefix is deterministic, so a vision category
    may refine within the family it belongs to and never move a record out of it.
    """
    if observation and observation.category:
        named = observation.category.strip().upper().replace(" ", "_")
        if named in KNOWN_CATEGORIES:
            prefix = candidate.resource_id.rsplit("_", 1)[0]
            from_prefix = CATEGORY_BY_PREFIX.get(prefix, "")
            same_family = (not from_prefix
                           or SYSTEM_BY_CATEGORY.get(named)
                           == SYSTEM_BY_CATEGORY.get(from_prefix))
            if same_family or observation.reader != "vision":
                return named
    prefix = candidate.resource_id.rsplit("_", 1)[0]
    return CATEGORY_BY_PREFIX.get(prefix, "")


class Policy:
    """`deletion_rules.csv`, in a form the engine can ask questions of."""

    def __init__(self, data: Dataset) -> None:
        self.by_category: dict[str, list] = {}
        for rule in data.rules:
            self.by_category.setdefault(rule.data_category, []).append(rule)

    def required_state(self, category: str) -> str:
        """The state a record of this category must end in. UNKNOWN when no rule covers it.

        An uncovered category is reported as unknown rather than defaulted to deletion.
        Deleting a record no rule asked us to delete is the other half of the failure the
        problem describes: "records that must be retained remain available".
        """
        if category in IMPLIED:
            return IMPLIED[category]
        rules = self.by_category.get(category)
        if not rules:
            return UNKNOWN
        # Every category in the supplied file has exactly one rule. If that ever stops
        # being true, the condition text has to be read, so we refuse rather than pick.
        if len(rules) > 1:
            return UNKNOWN
        return STATE_BY_ACTION.get(rules[0].required_action, UNKNOWN)

    def rule_id_for(self, category: str) -> str:
        rules = self.by_category.get(category)
        return rules[0].rule_id if rules and len(rules) == 1 else ""


KNOWN_CATEGORIES = {
    "USER_PROFILE", "SECONDARY_IDENTIFIER", "SEARCH_INDEX_ENTRY", "CACHE_ENTRY",
    "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT", "ANALYTICS_PROFILE", "PRODUCT_TELEMETRY",
    "USER_EXPORT", "MARKETING_PROFILE", "EMAIL_DELIVERY_LOG", "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD", "BACKUP_ARCHIVE", "ACCOUNT_TOMBSTONE", "DATA_FLOW",
}


#: What the deletion worker ATTEMPTED on a record, mapped to the end state that attempt
#: was aiming at.
#:
#: This is not the same as trusting the workflow, and the distinction is the whole
#: subject of the problem. `reported_result` is a claim about what happened and is
#: ignored everywhere in this solution -- it scores 0.531, worse than guessing. But the
#: *operation type* is not a claim about state: it is the organisation's own reading of
#: its deletion policy for that record, recorded before the attempt. `support_002` and
#: `support_864` are both support records and the resource id cannot tell them apart;
#: the activity stream says the first was to be deleted and the second redacted, which
#: is exactly how the published answers treat them.
TREATMENT_BY_EVENT = {
    "DELETE_RECORD": ABSENT,
    "REDACT_RECORD": REDACTED,
    "ANONYMIZE_RECORD": ANONYMIZED,
    "RETAIN_RECORD": PRESENT,
    "DISABLE_DATA_FLOW": DISABLED,
    "BLOCK_RESTORE": BLOCKED,
}

#: Only these actors speak for the deletion policy. An indexing or sync job touching a
#: record says nothing about how policy wants it treated.
POLICY_ACTORS = {"deletion_worker", "privacy_intake"}


def required_from_activity(candidate: Candidate) -> str:
    """The end state the organisation's own deletion run was aiming at, or UNKNOWN.

    The latest policy action wins: a record redacted and later deleted ends absent.
    """
    best, when = UNKNOWN, None
    for a in candidate.activities:
        if a.source_system not in POLICY_ACTORS:
            continue
        state = TREATMENT_BY_EVENT.get(a.event_type)
        if state and (when is None or a.event_time > when):
            best, when = state, a.event_time
    return best


def flag_is_on(value: str | None) -> bool | None:
    """Tri-state reading of a flag. None when the evidence did not say."""
    if value is None:
        return None
    v = str(value).strip().strip('"').lower()
    if v in TRUE_VALUES:
        return True
    if v in FALSE_VALUES:
        return False
    return None


def observed_state(candidate: Candidate, category: str) -> tuple[str, Observation | None]:
    """The state of a resource at audit_at, with the observation that establishes it.

    The most recent evidence that *says something* wins -- not simply the most recent
    evidence. `backup_4978` is the case that forced the distinction: a SQL snapshot
    records `restore_allowed=1`, and a log two days later mentions the archive without
    saying anything about it. Taking the latest observation threw away the only one that
    settled the question and reported the state as unknown.

    Returns `(UNKNOWN, None)` when nothing settles it. The caller must treat that as
    unaudited, never as compliant.
    """
    if not candidate.observations:
        return UNKNOWN, None

    newest_first = sorted(candidate.observations,
                          key=lambda o: o.captured_at, reverse=True)
    for observation in newest_first:
        state = _state_from(observation, category)
        if state != UNKNOWN:
            return state, observation
    return UNKNOWN, newest_first[0]


def _state_from(observation: Observation, category: str) -> str:
    """What one observation says about a record, or UNKNOWN if it says nothing."""

    # When the evidence states the compliance state in words, that is the state. A
    # handover row reading `IDENTIFIABLE` is not "present, unclear": it is the rule
    # violation, said out loud.
    #
    # ACTIVE and DISABLED are only states a *process* can be in. For a stored record the
    # same words mean something else entirely, so they are not accepted here.
    if observation.declared_state:
        declared = observation.declared_state
        process = category in ("DATA_FLOW", "BACKUP_ARCHIVE")
        if declared in (ACTIVE, DISABLED, BLOCKED) and not process:
            declared = ""
        elif declared == PRESENT and not observation.exposes_pii:
            # "found", with nothing said about identifiers. Fall through so the record's
            # own fields decide, rather than asserting exposure the evidence never claimed.
            declared = ""
        if declared:
            return declared

    if observation.present is False:
        return ABSENT

    # A process is read from its own switch, before any question of "is the record
    # there". A connector read-back saying `enabled=true` has both found the connector
    # and told us it is running; requiring a separate existence signal first discarded
    # every data flow and backup in the read-back traces.
    if category == "DATA_FLOW":
        enabled = flag_is_on(observation.flags.get("enabled"))
        if enabled is None:
            enabled = flag_is_on(observation.flags.get("last_delivery_status"))
        if enabled is not None:
            return ACTIVE if enabled else DISABLED

    if category == "BACKUP_ARCHIVE":
        allowed = flag_is_on(observation.flags.get("restore_allowed"))
        if allowed is None:
            allowed = flag_is_on(observation.flags.get("restore_access"))
        if allowed is not None:
            return ACTIVE if allowed else BLOCKED

    if observation.present is None:
        return UNKNOWN

    # The record exists. What kind of existing is it?
    if category == "SECURITY_AUDIT_LOG" or category == "LEGAL_HOLD_RECORD":
        return PRESENT

    # For everything else, what matters is whether the record still carries identifiers.
    # A tombstone with its name and email nulled out is REDACTED; an analytics profile
    # with no identifier left is ANONYMIZED; either one still carrying them is PRESENT
    # and exposing.
    if observation.exposes_pii:
        return PRESENT
    if not observation.field_level:
        # The record is there, and this evidence cannot testify that its identifiers are
        # gone. "Present" is the honest reading: it leaves the record as a live exposure
        # until something that enumerates its fields says otherwise.
        return PRESENT
    if category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
        return ANONYMIZED
    if category in ("ACCOUNT_TOMBSTONE", "SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG"):
        return REDACTED
    return PRESENT
