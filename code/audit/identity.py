"""Identity resolution: the step the ghost in the story got past.

The customer came back as a ghost because an old identifier was attached to nothing. So
the subject of a case is not one email address: it is every identifier that has ever been
attached to the person, because older systems and older evidence still carry the old ones.

Two rules hold throughout:

* **Exact, case-folded equality. Never substring.** The SQL snapshots deliberately place
  `jonas.berg@outlook.com`, `jonas.berglund@outlook.com` and `joana.berg@outlook.com` in
  the same table. A substring match ties all three to one person and invents exposures
  that do not exist.
* **Ambiguity is refused, not resolved.** If a request email maps to more than one user,
  we raise instead of picking. Auditing the wrong person's records is a worse outcome
  than failing to audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .dataset import Dataset, Identity

# Identity fields whose history we track. `name` is included because evidence carries
# display names, but it is held separately: names are not unique and must never be the
# only link between a record and a subject.
TRACKED = ("email", "phone", "email_hash")


class IdentityError(Exception):
    """Raised when the subject of a case cannot be established beyond doubt."""


def norm(value: str) -> str:
    """Case-folded, trimmed. Evidence is inconsistent about case.

    The shift-handover file contains `CHOI.JIHOON94@GMAIL.COM` in upper case next to
    `y.tanaka32@gmail.com` in lower case, so comparing raw strings silently misses rows.
    """
    return value.strip().casefold()


@dataclass(slots=True)
class Subject:
    """One person, with every identifier ever attached to them."""

    user_id: str
    name: str
    emails: set[str] = field(default_factory=set)        # normalised
    phones: set[str] = field(default_factory=set)        # normalised
    email_hashes: set[str] = field(default_factory=set)  # normalised
    names: set[str] = field(default_factory=set)         # normalised
    #: audit_id -> what changed, kept because a finding may need to cite an audit_id
    history: dict[str, str] = field(default_factory=dict)

    @property
    def identifiers(self) -> set[str]:
        """Every strong identifier. Names are excluded on purpose: not unique."""
        return self.emails | self.phones | self.email_hashes | {norm(self.user_id)}

    def matches(self, value: str) -> bool:
        """True when `value` is one of this subject's strong identifiers, exactly."""
        return norm(value) in self.identifiers

    def mentioned_in(self, text: str) -> set[str]:
        """Which of this subject's identifiers appear in a block of text.

        The haystack is normalised once and each identifier is looked for as a whole
        token, so `jonas.berg@outlook.com` cannot be found inside
        `jonas.berglund@outlook.com`.
        """
        hay = norm(text)
        found = set()
        for ident in self.identifiers:
            if not ident:
                continue
            start = hay.find(ident)
            while start != -1:
                before = hay[start - 1] if start else " "
                after_pos = start + len(ident)
                after = hay[after_pos] if after_pos < len(hay) else " "
                if not (_is_ident_char(before) or _is_ident_char(after)):
                    found.add(ident)
                    break
                start = hay.find(ident, start + 1)
        return found


def _is_ident_char(ch: str) -> bool:
    """Characters that can continue an email, phone or hash token."""
    return ch.isalnum() or ch in "._%+-@"


class IdentityIndex:
    """Every subject, indexed by every identifier they have ever had."""

    def __init__(self, data: Dataset) -> None:
        self._subjects: dict[str, Subject] = {}
        self._by_identifier: dict[str, set[str]] = {}
        self._build(data)

    # -- construction ------------------------------------------------------------- #

    def _build(self, data: Dataset) -> None:
        for ident in data.identities:
            self._subjects[ident.user_id] = _subject_from(ident)

        # The audit log is the only route to identifiers the current snapshot no longer
        # shows. Both sides of every change are kept: `new_value` can also be historical
        # if the field changed again later.
        for entry in data.audit_log:
            subject = self._subjects.get(entry.user_id)
            if subject is None:
                # An audit row for an unknown user is a data problem, not something to
                # paper over by inventing a subject.
                continue
            if entry.field_name not in TRACKED and entry.field_name != "name":
                continue
            bucket = {
                "email": subject.emails, "phone": subject.phones,
                "email_hash": subject.email_hashes, "name": subject.names,
            }[entry.field_name]
            for value in (entry.old_value, entry.new_value):
                if value:
                    bucket.add(norm(value))
            subject.history[entry.audit_id] = (
                f"{entry.field_name} {entry.old_value!r} -> {entry.new_value!r} "
                f"at {entry.event_time.isoformat()}")

        for user_id, subject in self._subjects.items():
            for ident in subject.identifiers:
                if ident:
                    self._by_identifier.setdefault(ident, set()).add(user_id)

    # -- lookup ------------------------------------------------------------------- #

    def resolve(self, value: str) -> Subject:
        """Find the subject owning `value` (email, phone, hash or user_id).

        Raises when no subject owns it, or when more than one does.
        """
        key = norm(value)
        owners = self._by_identifier.get(key, set())
        if not owners:
            raise IdentityError(f"no subject owns identifier {value!r}")
        if len(owners) > 1:
            raise IdentityError(
                f"identifier {value!r} is shared by {sorted(owners)}; refusing to guess "
                "which person this case is about")
        return self._subjects[next(iter(owners))]

    def get(self, user_id: str) -> Subject | None:
        return self._subjects.get(user_id)

    def __len__(self) -> int:
        return len(self._subjects)

    @property
    def identifier_count(self) -> int:
        return len(self._by_identifier)


def _subject_from(ident: Identity) -> Subject:
    s = Subject(user_id=ident.user_id, name=ident.name)
    if ident.email:
        s.emails.add(norm(ident.email))
    if ident.phone:
        s.phones.add(norm(ident.phone))
    if ident.email_hash:
        s.email_hashes.add(norm(ident.email_hash))
    if ident.name:
        s.names.add(norm(ident.name))
    return s
