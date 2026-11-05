"""Reading evidence into one shape.

The corpus looks like 46 different file families. It is not. Every family states some
subset of the same five things:

    which system, which resource, what kind of record, what state it is in,
    and which person it belongs to

So this module parses into a single `Observation` and nothing else. Ten of the eleven log
formats are a timestamp, a service, an event name and a bag of `key=value` pairs, so they
share one tokeniser rather than one regex each; the structured families (SQLite snapshots,
JSON bundles, service exports, the shift handover) get a reader apiece because their shape
carries meaning a tokeniser would throw away.

What this module deliberately does **not** do is decide anything. It reports what a file
says. Whether a stored email is a policy violation depends on `deletion_rules.csv`, and
that judgement lives in the policy stage. Keeping extraction and judgement apart is what
makes it possible to test them separately, and it is why a parser bug cannot quietly
become a wrong verdict.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .dataset import Dataset, EvidenceFile, parse_time
from .identity import norm

# --------------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------------- #

#: resource_id prefix -> system_id. Taken from the published sample answers, which are
#: the only authority on which system owns which resource family.
SYSTEM_BY_PREFIX = {
    "account": "account_service",
    "search": "search_service",
    "analytics": "analytics_platform",
    "support": "support_platform",
    "export": "export_service",
    "data_flow": "integration_service",
    "backup": "backup_service",
    "audit_record": "security_service",
    "tombstone": "identity_service",
}

#: SQLite table / JSON collection -> the data category the rules are written against.
CATEGORY_BY_COLLECTION = {
    "customer_profiles": "USER_PROFILE",
    "customer_profiles_primary": "USER_PROFILE",
    "customer_profiles_failover_replica": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "search_documents_primary": "SEARCH_INDEX_ENTRY",
    "customer_analytics_profiles": "ANALYTICS_PROFILE",
    "support_records": "SUPPORT_MESSAGE",
    "customer_exports": "USER_EXPORT",
    "connector_subscriptions": "DATA_FLOW",
    "backup_restore_entries": "BACKUP_ARCHIVE",
    "security_audit_records": "SECURITY_AUDIT_LOG",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    # Section names used by the JSON bundles and the per-service exports. Without these
    # a record falls back to its resource prefix, which cannot tell a support attachment
    # (deleted outright, rule_06) from a support conversation (redacted, rule_05).
    "support_conversations": "SUPPORT_MESSAGE",
    "tickets": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "profiles": "ANALYTICS_PROFILE",
    "index_queries": "SEARCH_INDEX_ENTRY",
    "profile_lookups": "USER_PROFILE",
    "connector_configurations": "DATA_FLOW",
    "connectors": "DATA_FLOW",
    "backup_catalog": "BACKUP_ARCHIVE",
    "restore_entries": "BACKUP_ARCHIVE",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "audit_records": "SECURITY_AUDIT_LOG",
    "customer_export_jobs": "USER_EXPORT",
    "exports": "USER_EXPORT",
    "retained_order_records": "LEGAL_HOLD_RECORD",
}

#: Which system owns each data category. Needed because the strongest proof of absence
#: is an EMPTY enumeration -- `customer_data_inventory_20260905.sql` creates every table
#: and inserts nothing -- and an empty table has no record to read a system from. Taking
#: the system from the collection name instead is what makes those files usable.
SYSTEM_BY_CATEGORY = {
    "USER_PROFILE": "account_service",
    "SECONDARY_IDENTIFIER": "account_service",
    "SEARCH_INDEX_ENTRY": "search_service",
    "ANALYTICS_PROFILE": "analytics_platform",
    "PRODUCT_TELEMETRY": "analytics_platform",
    "MARKETING_PROFILE": "analytics_platform",
    "SUPPORT_MESSAGE": "support_platform",
    "SUPPORT_ATTACHMENT": "support_platform",
    "USER_EXPORT": "export_service",
    "DATA_FLOW": "integration_service",
    "BACKUP_ARCHIVE": "backup_service",
    "SECURITY_AUDIT_LOG": "security_service",
    "LEGAL_HOLD_RECORD": "security_service",
    "ACCOUNT_TOMBSTONE": "identity_service",
}

#: Fields that count as direct identifiers wherever they appear. rule_15 names exactly
#: these for an account tombstone, and the same set is what makes any other record
#: "still attributable to a user".
PII_FIELDS = ("name", "full_name", "display_name", "requester_name",
              "email", "owner_email", "customer_email", "requester_email",
              "phone", "owner_phone", "requester_phone",
              "email_hash")

#: Canonical name for each PII field above, so a tombstone and a profile are comparable.
PII_CANONICAL = {
    "name": "name", "full_name": "name", "display_name": "name",
    "requester_name": "name",
    "email": "email", "owner_email": "email", "customer_email": "email",
    "requester_email": "email",
    "phone": "phone", "owner_phone": "phone", "requester_phone": "phone",
    "email_hash": "email_hash",
}

#: Values that mean "this lookup found nothing", i.e. the record is absent.
ABSENT_RESULTS = {"not_found", "absent", "missing", "deleted", "none"}
PRESENT_RESULTS = {"found", "present", "hit", "exists", "identifiable", "attributable"}

#: Evidence does not only say whether a record exists; some of it states the record's
#: compliance state outright. The shift handover is the clearest case: a row reading
#: `analytics_2034 | ANALYTICS_PROFILE | IDENTIFIABLE` is not merely "present", it is
#: "present and still attributable", which is the rule_07 violation itself. Reading these
#: words as "state unknown" is what made three of sample case_11's four findings vanish.
DECLARED_STATES = {
    "not_found": "ABSENT", "absent": "ABSENT", "missing": "ABSENT", "deleted": "ABSENT",
    "found": "PRESENT", "present": "PRESENT", "exists": "PRESENT",
    "identifiable": "PRESENT", "attributable": "PRESENT",
    "redacted": "REDACTED",
    "anonymized": "ANONYMIZED", "anonymised": "ANONYMIZED",
    "active": "ACTIVE", "enabled": "ACTIVE",
    "disabled": "DISABLED", "inactive": "DISABLED",
    "blocked": "BLOCKED",
}

#: Placeholders that are prose, not identifiers. Indexing them would tie every record
#: carrying the same placeholder to the same imaginary person.
NOT_IDENTIFIERS = {"no direct identifier", "none", "null", "n/a", "-", "unknown",
                   "redacted", "anonymized", "anonymised"}

_KV = re.compile(r'([a-zA-Z_][\w.]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,|}\]]+))')
_RESOURCE = re.compile(r"\b((?:account|search|analytics|support|export|backup|tombstone"
                       r"|data_flow|audit_record)_\d+)\b")
#: Trace identifiers, in every shape the logs use: `trace_id=tr-123`, `requestId=tr-123`,
#: `[tr-123]`, the bare field in a pipe-delimited or syslog line, and `rb-...` readbacks.
_TRACE = re.compile(r"\b((?:tr|rb)-[\w-]+)\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_USER_ID = re.compile(r"\buser_\d+\b")
_PHONE = re.compile(r"(?<![\w.])\+\d[\d\s().-]{6,}\d(?![\w.])")

#: Fields a log reports as part of a record's contents, not as a search key. Their
#: presence -- even set to null -- means the line is enumerating the record.
_STORED_FIELDS = ("requester_name", "requester_email", "requester_phone",
                  "customer_email", "owner_email", "owner_phone", "display_name",
                  "full_name", "email", "phone", "email_hash")

#: Category names as they may appear in prose, for documents that state one.
KNOWN_CATEGORY_WORDS = (
    "SUPPORT_ATTACHMENT", "SUPPORT_MESSAGE", "LEGAL_HOLD_RECORD", "SECURITY_AUDIT_LOG",
    "BACKUP_ARCHIVE", "ACCOUNT_TOMBSTONE", "ANALYTICS_PROFILE", "MARKETING_PROFILE",
    "SEARCH_INDEX_ENTRY", "USER_EXPORT", "USER_PROFILE",
)


def system_for(resource_id: str) -> str | None:
    """Which system owns a resource id, by its prefix. None when unrecognised."""
    for prefix, system in SYSTEM_BY_PREFIX.items():
        if resource_id.startswith(prefix + "_"):
            return system
    return None


# --------------------------------------------------------------------------------- #
# The one shape
# --------------------------------------------------------------------------------- #

@dataclass(slots=True)
class Coverage:
    """A file that *enumerates* a system at a point in time.

    This is what makes absence provable. A log mentions whichever records happened to be
    touched, so finding nothing in it proves nothing. A point-in-time snapshot of
    `customer_profiles` is exhaustive for that collection, so a subject who does not
    appear in it has no profile -- and that is exactly how the published answers justify
    `VERIFY_RECORD_ABSENT`. Sample cases 01, 02 and 04 all cite evidence_54, a snapshot
    that contains no row about any of them; what it does contain are the decoys
    `karim.elmasri@gmail.com` and `m.rios.gil@outlook.com`.

    Only the structured readers record coverage. The log reader never does.
    """

    file_id: str
    captured_at: datetime
    system_id: str
    category: str
    subject_keys: set[str] = field(default_factory=set)
    resource_ids: set[str] = field(default_factory=set)

    def covers(self, identifiers: set[str]) -> bool:
        return bool(self.subject_keys & identifiers)


@dataclass(slots=True)
class Observation:
    """One statement a piece of evidence makes about one resource.

    `present` is tri-state on purpose. `None` means the evidence mentions the resource
    without establishing whether it exists -- a lookup that started and never completed,
    for instance. That is not the same as "absent", and collapsing the two is how an
    audit concludes a record is gone when the truth is that nobody looked.
    """

    file_id: str
    captured_at: datetime
    resource_id: str
    system_id: str
    category: str = ""
    present: bool | None = None
    #: normalised identifiers that tie this observation to a person
    subject_keys: set[str] = field(default_factory=set)
    #: canonical PII field -> the value still stored. Empty means none stored.
    pii: dict[str, str] = field(default_factory=dict)
    #: everything else the evidence stated: enabled, restore_allowed, retention_until...
    flags: dict[str, str] = field(default_factory=dict)
    #: a compliance state the evidence stated in so many words, if it did
    declared_state: str = ""
    reader: str = ""

    #: set when a log line reported the record's identifying fields explicitly, nulls
    #: included -- a readback rather than an incidental mention
    enumerated: bool = False

    @property
    def field_level(self) -> bool:
        """True when this observation came from evidence that enumerates the record's
        fields, and can therefore testify that an identifier is *gone*.

        An ordinary log line cannot. It mentions whichever fields the service happened
        to log, so seeing no email in it says nothing about whether the record still
        stores one. Reading that silence as "redacted" is how `support_002` and
        `analytics_9914` were declared compliant while the published answers report both
        as violations.

        The readback traces are the exception, and they say so themselves:

            support_ticket_read_completed resource_id=support_5569
                requester_name=null requester_email=mori.ren@gmail.com
                requester_phone=null

        `requester_name=null` is not silence. It is a positive statement that the field
        is empty, which is exactly what distinguishes an enumeration from a mention.
        """
        return self.reader != "log" or self.enumerated

    @property
    def exposes_pii(self) -> bool:
        return bool(self.pii)

    def add_subject(self, *values: str | None) -> None:
        for v in values:
            if v and norm(str(v)) not in NOT_IDENTIFIERS:
                self.subject_keys.add(norm(str(v)))

    def add_pii(self, source_field: str, value) -> None:
        """Record a stored identifier. `None` and the string "null" store nothing.

        The snapshot bundles express a redacted tombstone as JSON `null`, and the SQL
        snapshots express it as the literal text `null`. Both mean the field was removed,
        so both must be treated as absence of PII, not as a value named "null".
        """
        if value is None:
            return
        text = str(value).strip()
        if not text or text.lower() in ("null", "none", "redacted", "anonymized"):
            return
        canonical = PII_CANONICAL.get(source_field)
        if canonical:
            self.pii[canonical] = text
            if canonical != "name":          # names are not unique; never a sole link
                self.subject_keys.add(norm(text))


# --------------------------------------------------------------------------------- #
# Readers
# --------------------------------------------------------------------------------- #

def kv_pairs(line: str) -> dict[str, str]:
    """Every field on a line, whatever shape the format writes them in.

    Handles the observability formats at once: bare `k=v`, quoted `k="v"`, the syslog
    prefix, the pipe-delimited stream, the escaped-JSON-in-a-message variant -- and
    lines that are a JSON object outright.

    That last case was missed for a long time and cost more than it looked like. Two of
    the log formats write

        2026-09-16T08:52:49Z {"logger":"security_service","trace_id":"tr-9028396",
                              "event":"audit_record_query_started","subject_ref":"user_61"}

    and a `key=value` regex finds nothing in it, because JSON separates with a colon.
    Resource ids and trace ids were still picked up by their own patterns, so the lines
    looked read -- while every field that says WHOSE record it is, and what the read
    returned, was being dropped in silence.
    """
    out: dict[str, str] = {}

    start = line.find("{")
    if start != -1 and line.rstrip().endswith("}"):
        try:
            document = json.loads(line[start:])
        except json.JSONDecodeError:
            document = None
        if isinstance(document, dict):
            for name, value in document.items():
                if isinstance(value, (str, int, float, bool)):
                    out[str(name).lower()] = str(value).strip()

    nested: list[str] = []
    for name, quoted, bare in _KV.findall(line):
        value = (quoted if quoted else bare).strip()
        out.setdefault(name.lower(), value.replace(chr(92) + chr(34), chr(34)))
        if "=" in value:
            nested.append(value)

    # A wrapper field can hold a whole record:
    #
    #     message="resource_id=\"account_66777\" rows=\"1\""
    #
    # The escaping is what delimits the nesting, so the line is tokenised FIRST -- the
    # pattern already allows escaped quotes inside a quoted value, which makes `message`
    # capture the whole inner record -- and only then is that value unescaped and
    # tokenised in turn. Unescaping the line up front destroys the delimiter and the
    # inner fields are lost, which is the mistake this comment exists to prevent.
    escaped = chr(92) + chr(34)
    for value in nested:
        for name, quoted, bare in _KV.findall(value.replace(escaped, chr(34))):
            out.setdefault(name.lower(), (quoted if quoted else bare).strip())
    return out


def _result_to_present(value: str | None) -> bool | None:
    if not value:
        return None
    v = value.strip().strip('"').lower()
    if v in ABSENT_RESULTS:
        return False
    if v in PRESENT_RESULTS:
        return True
    return None


#: What reading a point-in-time snapshot legitimately needs. Everything outside this set
#: is refused, so an evidence file cannot reach the filesystem or run a statement whose
#: purpose is something other than describing records.
#:
#: The list was not guessed: an authorizer was first run in trace mode over a real
#: snapshot to see what it actually asks for. It needs to create tables and indexes,
#: insert rows, read them back, run a transaction, reindex, and set one pragma. The
#: internal UPDATE on `sqlite_master` is SQLite bookkeeping, not the file writing to a
#: table.
_SQL_ALLOWED = frozenset({
    sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_TABLE,
    sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_INSERT, sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_REINDEX,
    sqlite3.SQLITE_ANALYZE, sqlite3.SQLITE_FUNCTION,
})

#: Pragmas a snapshot may set. Every other pragma is refused, because several of them
#: touch the filesystem or the schema in ways a data file has no business doing --
#: `writable_schema` and `temp_store_directory` among them.
_SQL_ALLOWED_PRAGMAS = frozenset({
    "foreign_keys", "encoding", "page_size", "user_version", "legacy_file_format",
    "synchronous", "auto_vacuum", "cache_size",
})


def _confined(action, arg1, arg2, database, trigger):      # noqa: ARG001
    """Authorizer for evidence SQL: deny by default, allow a short, traced list.

    Executing a file somebody else wrote is a real surface, not a theoretical one. A
    snapshot containing

        ATTACH DATABASE '/somewhere/else.db' AS out;
        CREATE TABLE out.x (c);

    writes a file outside the in-memory database. That was tried before this guard
    existed, and it worked.

    Deny-by-default rather than a block list: a block list only stops the attacks
    somebody already thought of, and these files are executed before anyone has read
    them.
    """
    if action == sqlite3.SQLITE_PRAGMA:
        return (sqlite3.SQLITE_OK if str(arg1).lower() in _SQL_ALLOWED_PRAGMAS
                else sqlite3.SQLITE_DENY)
    return sqlite3.SQLITE_OK if action in _SQL_ALLOWED else sqlite3.SQLITE_DENY


class EvidenceReader:
    """Parses the corpus once, into observations.

    The corpus is fixed: the same 94 files answer all 518 cases. So it is read once and
    queried many times, which is also what keeps the model-call count down -- the only
    files that need a model are the images and PDFs, and they are read once each too.
    """

    def __init__(self, data: Dataset) -> None:
        self.data = data
        self.observations: list[Observation] = []
        self.coverage: list[Coverage] = []
        #: Files we could not read at all. Each one is an unknown, and an unknown in an
        #: audit is a possible ghost, so this list is an alert.
        self.unread: list[tuple[str, str]] = []     # (file_id, why)
        #: Files we read successfully that contain nothing this audit can use -- a
        #: customer statement, a finance register, a console screen showing orders.
        #: Reported, never alerted on: "read and empty" is a fact, "could not read" is
        #: a problem, and collapsing them hides the second behind the first.
        self.accounted: list[tuple[str, str]] = []
        self._by_identifier: dict[str, set[int]] = {}
        #: collections a structured file declares, even when they hold no records.
        #: An empty `customer_profiles` snapshot is the strongest possible proof of
        #: absence, so it has to be registered rather than inferred from silence.
        self._declared: list[tuple[str, datetime, str, str]] = []

    # -- entry point -------------------------------------------------------------- #

    def read_all(self, *, families: set[str] | None = None) -> None:
        for ev in self.data.evidence:
            if families and ev.family not in families:
                continue
            try:
                before = len(self.observations)
                noted = len(self.unread)
                self._read(ev)
                if (len(self.observations) == before and len(self.unread) == noted
                        and not any(f == ev.file_id for f, _ in self.accounted)):
                    # Only when the reader did not already say why. Appending a second,
                    # vaguer reason used to overwrite the real one: every screenshot was
                    # filed as "no observation extracted" instead of "needs a model".
                    self.unread.append((ev.file_id, "no observation extracted"))
            except Exception as why:                  # noqa: BLE001
                # A file we failed to read is recorded as unread, never skipped in
                # silence. An unread file is an unknown, and unknowns must be visible.
                self.unread.append((ev.file_id, f"{type(why).__name__}: {why}"))
        self._index()

    def _read(self, ev: EvidenceFile) -> None:
        path = ev.resolve(self.data.directory)
        name = path.name

        if ev.family == "databases":
            self._read_sqlite(ev, path)
        elif name.startswith("customer_data_snapshot_bundle"):
            self._read_snapshot_bundle(ev, path)
        elif name.startswith("service_resource_export"):
            self._read_service_export(ev, path)
        elif name.startswith("customer_account_handover"):
            self._read_handover(ev, path)
        elif path.suffix == ".json":
            self._read_record_list(ev, path)
        elif path.suffix == ".log":
            self._read_log(ev, path)
        elif path.suffix.lower() == ".pdf":
            self._read_document(ev, path)
        elif ev.family == "images":
            # Needs a vision model; handled by a separate, cached pass.
            self.unread.append((ev.file_id, f"multimodal ({path.suffix})"))
        else:
            self.unread.append((ev.file_id, f"no reader for {path.name}"))

    # -- SQLite snapshots --------------------------------------------------------- #

    def _read_sqlite(self, ev: EvidenceFile, path: Path) -> None:
        """Execute the snapshot in a confined connection and read its tables.

        The files are SQLite-compatible SQL, so they are executed rather than pattern
        matched: a regex over INSERT statements would mis-split any value containing a
        comma or a quote, and these files carry names and message excerpts.

        But executing a file someone else wrote is a real surface, not a theoretical one.
        A snapshot containing

            ATTACH DATABASE '/somewhere/else.db' AS out;
            CREATE TABLE out.x (c);

        writes a file outside the in-memory database. It was tried before this guard was
        written, and it worked. So the connection runs behind an authorizer that allows
        only what reading a snapshot needs -- creating tables, inserting rows, reading
        them back -- and refuses ATTACH, DETACH and PRAGMA outright. Nothing in the
        supplied corpus needs them, and a file that does is not a snapshot.
        """
        script = path.read_text(encoding="utf-8")
        conn = sqlite3.connect(":memory:")
        conn.set_authorizer(_confined)
        try:
            conn.executescript(script)
            conn.row_factory = sqlite3.Row
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")]
            total = 0
            for table in tables:
                if table == "snapshot_scope":
                    continue
                rows = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"')]
                total += len(rows)
                self._declare(ev, table, rows)
                for row in rows:
                    self._observation_from_row(ev, table, row)
            if total == 0:
                # An inventory that creates every table and inserts nothing. It yields
                # no observation and is the strongest proof of absence in the corpus,
                # so it is accounted for rather than reported as unread.
                self.accounted.append(
                    (ev.file_id, f"empty point-in-time snapshot of "
                                 f"{len(tables) - 1} collection(s); proves absence"))
        finally:
            conn.close()

    def _observation_from_row(self, ev: EvidenceFile, table: str, row: dict) -> None:
        resource_id = str(row.get("resource_id") or "").strip()
        if not resource_id:
            return

        # The replica tables store the record as a JSON blob; unwrap it so the replica
        # and the primary become comparable, which is what replication drift means.
        if "record_json" in row and row["record_json"]:
            try:
                inner = json.loads(row["record_json"])
            except json.JSONDecodeError:
                inner = {}
            collection = str(row.get("collection_name") or "")
            merged = {**inner, "resource_id": resource_id}
            obs = self._make(ev, resource_id, collection, reader=f"sqlite:{table}")
            obs.flags["table"] = table
            obs.flags["origin_system"] = str(row.get("origin_system") or "")
            self._fill(obs, merged)
            return

        obs = self._make(ev, resource_id, table, reader=f"sqlite:{table}")
        obs.flags["table"] = table
        self._fill(obs, row)

    # -- JSON snapshot bundles ---------------------------------------------------- #

    def _read_snapshot_bundle(self, ev: EvidenceFile, path: Path) -> None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for snapshot in doc.get("snapshots", []):
            collection = str(snapshot.get("collection") or "")
            store = str(snapshot.get("data_store") or "")
            self._declare(ev, collection, snapshot.get("records", []), system=store)
            for record in snapshot.get("records", []):
                resource_id = str(record.get("resource_id") or "").strip()
                if not resource_id:
                    continue
                obs = self._make(ev, resource_id, collection, system=store,
                                 reader="snapshot_bundle")
                self._fill(obs, record)

    # -- per-service JSON exports ------------------------------------------------- #

    def _read_service_export(self, ev: EvidenceFile, path: Path) -> None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for system, sections in (doc.get("service_exports") or {}).items():
            if not isinstance(sections, dict):
                continue
            for section, records in sections.items():
                if isinstance(records, list):
                    self._declare(ev, section, records, system=system)
                for record in records if isinstance(records, list) else []:
                    if not isinstance(record, dict):
                        continue
                    resource_id = str(record.get("resource_id") or "").strip()
                    if not resource_id:
                        continue
                    obs = self._make(ev, resource_id, section, system=system,
                                     reader="service_export")
                    self._fill(obs, record)

    # -- flat record lists (connector configs, manifests, ledgers, reports) ------- #

    def _read_record_list(self, ev: EvidenceFile, path: Path) -> None:
        doc = json.loads(path.read_text(encoding="utf-8"))
        collection = str(doc.get("collection") or "")
        for record in doc.get("records", []):
            if not isinstance(record, dict):
                continue
            resource_id = str(record.get("resource_id") or "").strip()
            if not resource_id:
                continue
            obs = self._make(ev, resource_id,
                             str(record.get("record_type") or collection),
                             system=str(record.get("system") or ""),
                             reader="record_list")
            self._fill(obs, record)

    # -- the shift handover ------------------------------------------------------- #

    def _read_handover(self, ev: EvidenceFile, path: Path) -> None:
        """`timestamp | system | resource_id | category | state | identifier`.

        This is the file that grounds sample case_11, so it is also the regression test
        for the whole retrieval idea.
        """
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.count("|") < 4:
                continue
            parts = [p.strip() for p in line.lstrip("- ").split("|")]
            try:
                captured = parse_time(parts[0])
            except ValueError:
                continue
            system, resource_id, category, state = parts[1], parts[2], parts[3], parts[4]
            identifier = parts[5] if len(parts) > 5 else ""
            obs = Observation(file_id=ev.file_id, captured_at=captured,
                              resource_id=resource_id,
                              system_id=system or system_for(resource_id) or "",
                              category=category,
                              present=_result_to_present(state),
                              declared_state=DECLARED_STATES.get(norm(state), ""),
                              reader="handover")
            obs.flags["state"] = state
            obs.add_subject(identifier)
            if obs.declared_state == "PRESENT" and norm(state) == "identifiable":
                # The word is the finding: the record still points at a person.
                obs.pii["declared"] = identifier or "identifiable"
            self.observations.append(obs)
            self._declared.append((ev.file_id, captured,
                                   obs.system_id, category))

    # -- PDF documents ------------------------------------------------------------ #

    def _read_document(self, ev: EvidenceFile, path: Path) -> None:
        """Read a PDF as text.

        These are ReportLab-generated business documents with real fonts, not scans, so
        the text comes out directly and no vision model is needed for any of them. That
        was worth checking before reaching for one: it is four of the fifteen files that
        looked multimodal, and `delivery_correction_attachment.pdf` is the evidence the
        published answer for sample case_07 cites.

        A document concerns one matter, so identifiers found anywhere in it apply to the
        resources it names -- the same whole-document reasoning the trace grouping does
        for logs.
        """
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if not text.strip():
            self.unread.append((ev.file_id, "PDF carries no extractable text"))
            return

        keys = {norm(m) for m in _EMAIL.findall(text)}
        keys |= {norm(m) for m in _USER_ID.findall(text)}
        keys |= {norm(m.strip()) for m in _PHONE.findall(text)}
        keys = {k for k in keys if k and k not in NOT_IDENTIFIERS}

        lowered = text.lower()
        named = [c for c in KNOWN_CATEGORY_WORDS if c.lower() in lowered]

        resources = sorted(set(_RESOURCE.findall(text)))
        if not resources:
            # Business documents that concern a person without naming a record in any
            # system we audit: a customer statement, a finance retention register. They
            # carry identity and context, not resources, and saying so precisely is the
            # difference between "read and empty" and "quietly skipped".
            self.accounted.append(
                (ev.file_id, f"document read; names no auditable resource "
                             f"({len(keys)} identifier(s) found)"))
            return

        for resource_id in resources:
            category = ""
            if resource_id.startswith("support_") and "attachment" in lowered:
                # rule_06: an attachment belonging only to the subject is deleted
                # outright, where a conversation with shared context is redacted. The
                # document says which kind it is; the resource id alone does not.
                category = "SUPPORT_ATTACHMENT"
            elif named:
                category = named[0]
            obs = Observation(file_id=ev.file_id, captured_at=ev.captured_at,
                              resource_id=resource_id,
                              system_id=system_for(resource_id) or "",
                              category=category, present=True, reader="document")
            obs.subject_keys |= keys
            for match in _EMAIL.findall(text):
                obs.add_pii("email", match)
            for match in _PHONE.findall(text):
                obs.add_pii("phone", match.strip())
            self.observations.append(obs)
            self._declared.append((ev.file_id, ev.captured_at, obs.system_id, category))

    # -- logs --------------------------------------------------------------------- #

    def _read_log(self, ev: EvidenceFile, path: Path) -> None:
        """One tokeniser for every log format, with lines joined by trace id.

        A single line is rarely a complete statement. Across all the observability
        formats the pattern is the same:

            ... [tr-6074163] profile_lookup_started    lookup_key="someone@example.com"
            ... [tr-6074163] profile_lookup_completed  resource_id="account_7023" rows="1"

        The identifier is on one line and the resource on another. Reading lines
        independently loses the link between them, and it loses it silently: the
        resource is still recorded, just belonging to nobody. That one mistake cost 27
        of the resources the published answers name -- more than any other cause.

        So lines are grouped by trace id first, and a trace's identifiers apply to every
        resource it touched. Lines with no trace stand alone, which is right for the
        formats that put everything on one line.
        """
        traces: dict[str, dict] = {}
        order: list[str] = []

        for n, line in enumerate(path.read_text(encoding="utf-8",
                                                errors="replace").splitlines()):
            if not line.strip():
                continue
            kv = kv_pairs(line)

            resource_id = kv.get("resource_id", "")
            if not resource_id:
                found = _RESOURCE.search(line)
                resource_id = found.group(1) if found else ""

            keys = [kv.get(k) for k in ("subject_reference", "lookup_key",
                                        "correlation_key", "match_key", "subject_key",
                                        "subject_ref", "customer_email",
                                        "customer_reference")]
            keys = [k for k in keys if k]
            if not resource_id and not keys:
                continue

            found_trace = _TRACE.search(line)
            trace = (kv.get("trace_id") or kv.get("requestid")
                     or (found_trace.group(1) if found_trace else "") or f"line:{n}")
            group = traces.get(trace)
            if group is None:
                group = {"keys": set(), "resources": {}}
                traces[trace] = group
                order.append(trace)
            for k in keys:
                if norm(k) not in NOT_IDENTIFIERS:
                    group["keys"].add(norm(k))
            if not resource_id:
                continue

            system = (kv.get("system") or kv.get("service") or kv.get("logger")
                      or kv.get("function") or "")
            if system.endswith("_replica"):
                system = system[: -len("_replica")]

            entry = group["resources"].get(resource_id)
            if entry is None:
                entry = {"time": self._line_time(line) or ev.captured_at,
                         "system": system_for(resource_id) or system,
                         "category": kv.get("record_type", ""),
                         "present": None, "flags": {}, "pii": {},
                         "enumerated": False}
                group["resources"][resource_id] = entry

            # A PII scan is the platform saying, in its own words, that this record
            # still contains an identifier:
            #
            #   WARN ... resource_id=support_9553 event=message_pii_scan
            #        matched_value="e.varga90@yahoo.com" detector=direct_identifier
            #
            # That settles two things at once -- whose record it is, and that it is
            # exposing. It deliberately does NOT mark the line as a field enumeration:
            # a scan reports what it matched, not the whole record, so it can prove an
            # identifier is there and never that the others are gone.
            matched = kv.get("matched_value")
            if matched and "pii" in kv.get("event", "").lower():
                if norm(matched) not in NOT_IDENTIFIERS:
                    entry["pii"]["email" if "@" in matched else "value"] = matched
                    group["keys"].add(norm(matched))
                entry["present"] = True

            # Stored record fields, as opposed to the key the service searched by.
            # `lookup_key` is what someone asked for; `requester_email` is what the
            # record still holds. Only the second is an exposure.
            for name in _STORED_FIELDS:
                if name not in kv:
                    continue
                entry["enumerated"] = True
                value = kv[name]
                if norm(value) not in NOT_IDENTIFIERS:
                    entry["pii"][PII_CANONICAL.get(name, name)] = value
            state = self._log_present(kv)
            if state is not None:
                entry["present"] = state          # the latest result in the trace wins
            if kv.get("record_type"):
                entry["category"] = kv["record_type"]
            for key in ("event", "result", "rows", "http_status", "enabled",
                        "restore_allowed", "last_delivery_status", "connector_name",
                        "marker_found", "index", "integrity_check", "retention_until"):
                if key in kv:
                    entry["flags"][key] = kv[key]

        for trace in order:
            group = traces[trace]
            for resource_id, entry in group["resources"].items():
                obs = Observation(
                    file_id=ev.file_id, captured_at=entry["time"],
                    resource_id=resource_id, system_id=entry["system"],
                    category=CATEGORY_BY_COLLECTION.get(entry["category"],
                                                        entry["category"]),
                    present=entry["present"], reader="log",
                    enumerated=entry["enumerated"])
                obs.flags.update(entry["flags"])
                obs.pii.update(entry["pii"])
                if entry["enumerated"] and obs.present is None:
                    # A readback that reported this record's fields found the record.
                    obs.present = True
                obs.subject_keys |= group["keys"]
                declared = DECLARED_STATES.get(norm(entry["flags"].get("result", "")), "")
                if declared:
                    obs.declared_state = declared
                self.observations.append(obs)

    @staticmethod
    def _line_time(line: str) -> datetime | None:
        head = line[:20].strip()
        try:
            return parse_time(head)
        except ValueError:
            return None

    @staticmethod
    def _log_present(kv: dict[str, str]) -> bool | None:
        state = _result_to_present(kv.get("result"))
        if state is not None:
            return state
        rows = kv.get("rows")
        if rows is not None and rows.isdigit():
            return int(rows) > 0
        status = kv.get("http_status")
        if status == "404":
            return False
        if status == "200" and kv.get("event", "").endswith("_completed"):
            return True
        return None

    # -- shared --------------------------------------------------------------------#

    def _make(self, ev: EvidenceFile, resource_id: str, collection: str, *,
              system: str = "", reader: str = "") -> Observation:
        obs = Observation(
            file_id=ev.file_id, captured_at=ev.captured_at, resource_id=resource_id,
            system_id=system_for(resource_id) or system,
            category=CATEGORY_BY_COLLECTION.get(collection, collection),
            present=True, reader=reader)
        self.observations.append(obs)
        return obs

    @staticmethod
    def _fill(obs: Observation, record: dict) -> None:
        """Copy a record's fields into an observation, splitting PII from the rest."""
        for key, value in record.items():
            low = key.lower()
            if low in ("observed_at", "captured_at", "recorded_at", "snapshot_at"):
                # A record often carries its own observation time, which is more precise
                # than the file's. The audit_at cutoff is only as good as this.
                try:
                    obs.captured_at = parse_time(str(value))
                except (ValueError, TypeError):
                    obs.flags[low] = str(value or "")
            elif low == "status_code":
                # A lookup section reports what the lookup returned. 404 is not a record
                # that exists; it is the service saying there is none. Reading these
                # sections as "present" reported three already-deleted profiles as
                # remaining, and turned three correct COMPLETE verdicts into INCOMPLETE.
                text = str(value or "")
                obs.flags[low] = text
                if text.startswith("4") or text.startswith("5"):
                    obs.present = False
                elif text == "200":
                    obs.present = True
            elif low in ("profile", "record", "document", "entry") and value is None:
                # The section names the resource and states that its payload is empty.
                obs.present = False
            elif low in PII_FIELDS:
                obs.add_pii(low, value)
            elif low in ("customer_reference", "subject_reference", "user_id",
                         "subject_ref", "owner_reference"):
                obs.add_subject(value)
            elif low == "account_status":
                # `account_status` describes the ACCOUNT, not this record's existence.
                # A tombstone row reading DELETED is a row that exists -- that is the
                # whole point of a tombstone -- and mapping it to ABSENT hid the fact
                # that tombstone_9178 still carried a name, email, phone and hash. A
                # profile row reading ACTIVE is simply a profile that is there; the row
                # being in the table already proved that.
                obs.flags[low] = str(value or "")
            elif low in ("result", "status", "state"):
                text = str(value or "")
                obs.flags[low] = text
                decided = _result_to_present(text)
                if decided is not None:
                    obs.present = decided
                if not obs.declared_state:
                    obs.declared_state = DECLARED_STATES.get(norm(text), "")
            elif low not in ("resource_id", "record_json"):
                obs.flags[low] = "" if value is None else str(value)

    # -- querying ------------------------------------------------------------------#

    def read_images(self, vision) -> int:
        """Second pass over the files the text readers could not open.

        Kept separate from `read_all` so the pipeline runs, and is testable, with no
        model at all. A screenshot never registers coverage: a console screen shows what
        someone looked up, not everything a system holds, so finding nothing in one
        proves nothing.
        """
        added = 0
        remaining: list[tuple[str, str]] = []
        by_id = self.data.evidence_by_id()
        for file_id, why in self.unread:
            if "multimodal" not in why:
                remaining.append((file_id, why))
                continue
            ev = by_id[file_id]
            before = len(vision.failures)
            found = vision.read(ev, ev.resolve(self.data.directory))
            if found:
                self.observations.extend(found)
                added += len(found)
            elif len(vision.failures) > before:
                remaining.append((file_id, f"vision pass failed: "
                                           f"{vision.failures[-1][1][:80]}"))
            else:
                # The screen was read. Several consoles show orders, tickets and
                # statements rather than records in a system this audit covers, and
                # anything whose identifier is not in a known family is dropped on
                # purpose -- a screenshot is the one source that can invent one.
                self.accounted.append(
                    (file_id, "screen read; names no auditable resource"))
        self.unread = remaining
        self._index()
        return added

    def _declare(self, ev: EvidenceFile, collection: str, records, *,
                 system: str = "") -> None:
        """Note that this file enumerates a collection, however many records it holds."""
        category = CATEGORY_BY_COLLECTION.get(collection, collection)
        resolved = system or SYSTEM_BY_CATEGORY.get(category, "")
        if not resolved:
            for record in records if isinstance(records, list) else []:
                if isinstance(record, dict):
                    guess = system_for(str(record.get("resource_id") or ""))
                    if guess:
                        resolved = guess
                        break
        if not resolved:
            # A collection we cannot place in a system cannot prove anything absent,
            # so it is not registered as coverage at all rather than registered uselessly.
            return
        self._declared.append((ev.file_id, ev.captured_at, resolved, category))

    def _index(self) -> None:
        self._by_identifier.clear()
        for i, obs in enumerate(self.observations):
            for key in obs.subject_keys:
                self._by_identifier.setdefault(key, set()).add(i)
        self._build_coverage()

    def _build_coverage(self) -> None:
        """Turn the declared collections into coverage, filled from their observations."""
        buckets: dict[tuple[str, str, str], Coverage] = {}

        def bucket(file_id: str, captured: datetime, system: str,
                   category: str) -> Coverage:
            key = (file_id, system, category)
            cov = buckets.get(key)
            if cov is None:
                cov = Coverage(file_id=file_id, captured_at=captured,
                               system_id=system, category=category)
                buckets[key] = cov
            return cov

        for file_id, captured, system, category in self._declared:
            bucket(file_id, captured, system, category)

        declared_files = {file_id for file_id, *_ in self._declared}
        for obs in self.observations:
            if obs.reader == "log" or obs.file_id not in declared_files:
                continue
            cov = bucket(obs.file_id, obs.captured_at, obs.system_id, obs.category)
            cov.subject_keys |= obs.subject_keys
            cov.resource_ids.add(obs.resource_id)

        self.coverage = sorted(buckets.values(), key=lambda c: c.captured_at)

    def proof_of_absence(self, system_id: str, identifiers: set[str], *,
                         not_after: datetime, category: str = "") -> Coverage | None:
        """The most recent enumeration of `system_id` in which the subject does not appear.

        Returns None when no file enumerates that system before the cutoff. None means
        "not established", and the caller must not read it as "absent": that conflation
        is the failure the whole problem is about.
        """
        best: Coverage | None = None
        for cov in self.coverage:
            if cov.captured_at > not_after or cov.system_id != system_id:
                continue
            if category and cov.category and cov.category != category:
                continue
            if cov.covers(identifiers):
                continue                       # the subject IS in it; nothing is proven
            if best is None or cov.captured_at > best.captured_at:
                best = cov
        return best

    def for_identifiers(self, identifiers: set[str], *,
                        not_after: datetime | None = None) -> list[Observation]:
        """Every observation tied to one of these exact identifiers.

        `not_after` enforces the `audit_at` cutoff here, at the query, so no later stage
        has to remember it. Evidence captured after a case's cutoff cannot reach it.
        """
        hits: set[int] = set()
        for key in identifiers:
            hits |= self._by_identifier.get(key, set())
        found = [self.observations[i] for i in sorted(hits)]
        if not_after is not None:
            found = [o for o in found if o.captured_at <= not_after]
        return found

    def stats(self) -> dict:
        by_reader: dict[str, int] = {}
        for obs in self.observations:
            by_reader[obs.reader] = by_reader.get(obs.reader, 0) + 1
        return {
            "observations": len(self.observations),
            "identifiers_indexed": len(self._by_identifier),
            "files_unread": len(self.unread),
            "by_reader": dict(sorted(by_reader.items(), key=lambda kv: -kv[1])),
        }
