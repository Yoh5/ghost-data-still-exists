"""Which resources belong to a subject: the step that decides the ceiling.

A resource we never list cannot be judged, remediated or verified, so this is the upper
bound on every later metric. It is also the step where the story's $2.4m failure actually
happened: the ghost survived because nobody could enumerate the copies.

Three linkage routes, measured on the 32 published answers (111 named resources):

    evidence names the subject's identifier alongside the resource     59/111
    system_activity.csv names the resource                             85/111
    either of the two                                                 100/111

So neither route is enough alone, and together they reach 90%. The remaining 10 are named
only inside images and PDFs, which a separate vision pass covers.

The hard part is that the activity stream is global: 4011 rows about many people, and a
row like

    activity_3814 | DELETE_RECORD | search_service | search_052 | FAILED

says nothing about whose record `search_052` is. What makes it attributable is that a
deletion request produces a **burst**: for sample case_11, activity_3801 through
activity_3817, all from `deletion_worker`, between 11:04 and 13:52 on one day, starting
with the one resource that evidence does tie to the subject. So linkage spreads from a
grounded seed through the burst, never from the burst alone. A resource reached only by
co-occurrence with another subject's run would be an invented exposure, which is why the
window is a measured parameter and not a guess.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .dataset import Activity, Dataset
from .evidence import EvidenceReader, Observation, system_for
from .identity import Subject, norm

#: Systems that run deletion work on behalf of a request. A burst is only trusted when it
#: comes from one of these, so unrelated background traffic cannot join a case.
#: Systems whose records policy requires us to KEEP (rule_12 security audit logs,
#: rule_13 legal holds). They are the one place where evidence captured after a case's
#: cutoff may still identify a resource.
#:
#: The reasoning is narrow and the safety comes from the engine, not from trust. A
#: retained record can never produce a finding -- its required state is PRESENT, so it is
#: a gap only if it is MISSING -- which means a late-identified one can only ever add a
#: `VERIFY_RECORD_PRESENT` step. And in a COMPLETE case every verification step must cite
#: evidence, so one with no timely evidence is dropped there rather than published. The
#: step therefore survives exactly where the spec says verification carries no citation:
#: an INCOMPLETE case describing future work.
RETAINED_SYSTEMS = {"security_service"}

DELETION_ACTORS = {"deletion_worker", "privacy_intake", "data_catalog"}

#: How many consecutive non-deletion activity ids a run may contain before it is
#: considered finished. Chosen by the sweep in code/evaluation/sweep_window.py.
#:
#: A deletion request writes a contiguous block of activity ids. For sample case_03,
#: activity_3851 deletes account_7566 and activity_3852 anonymises analytics_9406
#: twenty-four minutes later -- and that adjacency is the ONLY thing in the dataset
#: linking the analytics record to the person, because an anonymised record carries no
#: identifier by construction. Attribution by id contiguity reaches those records; the
#: time window that preceded it did not, and swept in whole runs belonging to other
#: people on the way.
DEFAULT_GAP = 0

#: How far from the seed a run may stretch in time. Contiguity says "the same block of
#: work", time says "the same day's work", and a run is both. Swept in
#: code/evaluation/sweep_attribution.py: at one hour the whole configuration matches
#: evidence-only attribution on case accuracy (0.969) while lifting step F1 from 0.758 to
#: 0.812 and field accuracy from 0.459 to 0.606. At three hours and beyond, adjacent
#: people's runs merge and two correct COMPLETE verdicts are lost.
DEFAULT_WINDOW = timedelta(hours=1)


@dataclass(slots=True)
class Candidate:
    """One resource that may belong to the subject, with why we think so."""

    resource_id: str
    system_id: str
    #: "evidence" | "activity-link" | "burst"; the weakest route that reached it
    via: str = ""
    observations: list[Observation] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    #: file_id of the enumeration that shows the subject is not in this system, set by
    #: the engine when absence had to be proven rather than observed.
    absence_proof: str = ""

    @property
    def grounded(self) -> bool:
        """True when a piece of evidence tied this resource to the subject directly.

        A candidate reached only through a burst is a lead, not a fact. Keeping the
        distinction lets the policy stage refuse to assert anything about a lead.
        """
        return self.via == "evidence"

    def latest_observation(self) -> Observation | None:
        """The most recent observation, which is the state that counts at audit_at.

        Older snapshots are kept because they prove a resource once existed, which is
        how absence becomes provable at all.
        """
        return max(self.observations, key=lambda o: o.captured_at, default=None)


class Inventory:
    """Builds each subject's resource list from evidence and activity."""

    def __init__(self, data: Dataset, reader: EvidenceReader, *,
                 gap: int = DEFAULT_GAP, use_burst: bool = True,
                 one_per_system: bool = True, seed_any_activity: bool = False,
                 late_retained: bool = True,
                 window: timedelta | None = None) -> None:
        self.data = data
        self.reader = reader
        self.gap = gap
        self.use_burst = use_burst
        self.one_per_system = one_per_system
        #: Whether ANY activity row on a grounded resource may locate the deletion run,
        #: or only a row written by a deletion actor. Swept; see sweep_attribution.py.
        self.seed_any_activity = seed_any_activity
        #: Whether evidence captured after the cutoff may identify a RETAINED
        #: record. It can only add a verification step, never a finding.
        self.late_retained = late_retained
        self.window = window or DEFAULT_WINDOW

        self._activity_by_resource: dict[str, list[Activity]] = collections.defaultdict(list)
        self._by_number: dict[int, Activity] = {}
        for a in data.activity:
            self._activity_by_resource[a.resource_id].append(a)
            self._by_number[_number(a)] = a

        #: file_id -> the manifest's capture time, which is what decides whether a
        #: piece of evidence may be used or cited for a given cutoff
        self._file_captured = {e.file_id: e.captured_at for e in data.evidence}

        #: resource -> every identifier any evidence has ever attached to it, used to
        #: throw out a lead the evidence gives to somebody else
        self._owners: dict[str, set[str]] = collections.defaultdict(set)
        for obs in reader.observations:
            self._owners[obs.resource_id] |= obs.subject_keys

        # Activity rows that state a link explicitly: "linked <resource> to <email> and
        # <user_id>". Only 12 rows, but they are the one unambiguous route, so they are
        # indexed rather than re-scanned.
        self._explicit: dict[str, set[str]] = collections.defaultdict(set)
        for a in data.activity:
            if a.event_type == "LINK_RESOURCE_IDENTITY":
                for token in _tokens(a.details):
                    self._explicit[token].add(a.resource_id)

    # -- public ------------------------------------------------------------------- #

    def resources_for(self, subject: Subject, audit_at: datetime) -> dict[str, Candidate]:
        """Every resource plausibly belonging to `subject`, as known at `audit_at`."""
        found: dict[str, Candidate] = {}

        # 1. Grounded seeds: evidence that names one of the subject's identifiers.
        #
        #    Linkage is cut off at `audit_at` like everything else. Letting later
        #    captures identify a resource was tried and measured: it is the only route
        #    to 7 of the resources the published answers name, and step recall did rise
        #    (0.513 -> 0.523). But it also drags in resources whose state at the cutoff
        #    cannot be established, which blocked two correct COMPLETE verdicts and took
        #    case-level accuracy from 0.781 down to 0.750 for no change in step F1
        #    (0.671 either way). Tightening the block to "only when timely evidence
        #    exists but is inconclusive" did not recover it. So the cutoff stays whole:
        #    a case is decided on what was knowable when it was audited.
        for obs in self.reader.for_identifiers(subject.identifiers, not_after=audit_at):
            self._ensure(found, obs.resource_id, obs.system_id, "evidence")

        # 1b. Retained records only: evidence from after the cutoff may name them.
        #     See RETAINED_SYSTEMS for why this cannot turn a verdict.
        if self.late_retained:
            for obs in self.reader.for_identifiers(subject.identifiers):
                if (system_for(obs.resource_id) or obs.system_id) in RETAINED_SYSTEMS:
                    self._ensure(found, obs.resource_id, obs.system_id, "evidence")

        # 2. Explicit links from the activity stream.
        for ident in subject.identifiers:
            for resource_id in self._explicit.get(ident, ()):
                self._ensure(found, resource_id, system_for(resource_id) or "",
                             "activity-link")

        # 3. Expand along the deletion run that touched each grounded seed.
        #
        #    A lead is only admitted if evidence does not give it to somebody else.
        #    Co-occurrence is not ownership: before that filter, sample case_11 emitted
        #    findings against search_5960 and analytics_5715 -- other people's records --
        #    and 123 spurious verification steps across the 32 cases. Inventing an
        #    exposure for an uninvolved person is worse than missing one.
        if self.use_burst:
            seeds = [c.resource_id for c in found.values()
                     if c.via in ("evidence", "activity-link")]
            for resource_id in seeds:
                for a in self._activity_by_resource.get(resource_id, ()):
                    if a.event_time > audit_at:
                        continue
                    if not self.seed_any_activity \
                            and a.source_system not in DELETION_ACTORS:
                        continue
                    block = [x for x in self._block(_number(a), a.event_time)
                             if x.event_time <= audit_at]

                    # A block that also touches somebody else's records is a stretch of
                    # the stream where two deletion runs meet. Its records that belong
                    # to a named person can still be sorted out; its records that belong
                    # to nobody visible cannot, and an anonymised record carries no
                    # identifier by construction. Both neighbours would claim it, and
                    # one of them would be wrong.
                    #
                    # Measured: `analytics_2265` was audited for user_34 AND user_35 --
                    # reachable by run from both, excludable by neither. Ambiguity is
                    # refused here for the same reason an ambiguous identity raises
                    # rather than picking a person.
                    #    The refusal is narrow on purpose. What makes a lead ambiguous
                    #    is not that the block touches someone else at all, but that it
                    #    touches someone else IN THE SAME SYSTEM: a person has one
                    #    analytics profile, so an unowned analytics record sitting beside
                    #    a stranger's analytics record could be either. A stranger's
                    #    search entry says nothing about an unowned backup.
                    #
                    #    Refusing every unowned lead in a mixed block was measured first
                    #    and is too blunt: precision 0.993 but recall 0.803 -> 0.756 and
                    #    F1 0.876 -> 0.859, because it also discards the anonymised
                    #    records this route exists to reach.
                    contested = set()
                    for x in block:
                        owners = self._owners.get(x.resource_id, set())
                        if owners and not (owners & subject.identifiers):
                            contested.add(system_for(x.resource_id) or x.target_system)

                    for other in block:
                        owners = self._owners.get(other.resource_id, set())
                        if owners and not (owners & subject.identifiers):
                            continue
                        if not owners and (system_for(other.resource_id)
                                           or other.target_system) in contested:
                            continue
                        self._ensure(found, other.resource_id,
                                     system_for(other.resource_id) or other.target_system,
                                     "burst")

        # 4. One resource per system.
        #
        #    Measured on the published answers: of the 111 resources they name, the
        #    number per (case, system) is 1 in 111 cases out of 111. A person has one
        #    profile, one search entry, one analytics record. So where this stage has
        #    produced several candidates in one system, at most one of them is the
        #    subject's and the rest are noise -- which is exactly the shape the deletion
        #    run's leads arrive in.
        if self.one_per_system:
            found = self._best_per_system(found, subject)

        # 5. Attach every activity row and observation we have for what we found, so the
        #    policy stage sees the whole record without querying again.
        # Two clocks, and they are not interchangeable. A record carries its own
        # observation time, which is what orders observations inside a file. But what
        # makes a piece of evidence ADMISSIBLE is the manifest's capture time for the
        # file, because that is the "evidence item" the spec forbids citing after a
        # case's cutoff. `evidence_06` is stamped 2026-09-18 and contains lines written
        # on 2026-09-16; using the line time to admit it meant citing a file captured
        # two days after the audit. The cutoff test caught it.
        by_resource: dict[str, list[Observation]] = {}
        for obs in self.reader.observations:
            captured = self._file_captured.get(obs.file_id)
            if captured is not None and captured > audit_at:
                continue
            if obs.captured_at <= audit_at:
                by_resource.setdefault(obs.resource_id, []).append(obs)

        for resource_id, cand in found.items():
            cand.activities = [a for a in self._activity_by_resource.get(resource_id, ())
                               if a.event_time <= audit_at]
            cand.observations = by_resource.get(resource_id, [])
        return found

    # -- internals ---------------------------------------------------------------- #

    def _best_per_system(self, found: dict[str, Candidate],
                         subject: Subject) -> dict[str, Candidate]:
        """Keep the single best-supported candidate in each system.

        Ranked by how well the evidence ties it to this person, not by recency: a
        resource evidence names alongside the subject always beats one reached by
        following a deletion run, however recent. Ties break on the resource id so the
        result is deterministic -- every number in this repository depends on the same
        inputs giving the same answer twice.
        """
        rank = {"evidence": 3, "activity-link": 2, "burst": 1}
        by_system: dict[str, list[Candidate]] = collections.defaultdict(list)
        for cand in found.values():
            by_system[cand.system_id or cand.resource_id].append(cand)

        kept: dict[str, Candidate] = {}
        for system, candidates in by_system.items():
            if len(candidates) == 1:
                best = candidates[0]
            else:
                best = max(candidates, key=lambda c: (
                    rank.get(c.via, 0),
                    len(self._owners.get(c.resource_id, set()) & subject.identifiers),
                    c.resource_id))
            kept[best.resource_id] = best
        return kept

    def _block(self, number: int, moment: datetime) -> list[Activity]:
        """The run of consecutive deletion-actor activity ids containing `number`.

        Two conditions, and neither works alone.

        *Contiguity* finds records that carry no identifier at all -- an anonymised
        analytics profile is unreachable any other way -- but consecutive runs belonging
        to different people are not separated by anything in the id stream, so on its own
        it hands one person's search entry to the two cases either side.

        *Time* separates those runs, because they happen days apart, but on its own a
        time window sweeps in every unrelated run that overlaps it.

        Together they say what is actually meant: the same deletion run. `self.gap`
        consecutive foreign ids are tolerated, because a run is not always perfectly
        contiguous in the global stream.
        """
        # The seed only gives a position. It joins the run only if it is itself a policy
        # action: an indexing or sync row on one of the subject's records tells us where
        # in the stream to look, not that the row belongs to the deletion.
        seed = self._by_number.get(number)
        found = [seed] if seed is not None and seed.source_system in DELETION_ACTORS \
            else []
        for step in (1, -1):
            i, missed = number, 0
            while True:
                i += step
                a = self._by_number.get(i)
                if a is None or a.source_system not in DELETION_ACTORS:
                    missed += 1
                    if missed > self.gap:
                        break
                    continue
                if abs(a.event_time - moment) > self.window:
                    break
                missed = 0
                found.append(a)
        return found

    @staticmethod
    def _ensure(found: dict[str, Candidate], resource_id: str, system_id: str,
                via: str) -> Candidate:
        if not resource_id:
            raise ValueError("empty resource_id")
        cand = found.get(resource_id)
        if cand is None:
            cand = Candidate(resource_id=resource_id,
                             system_id=system_for(resource_id) or system_id, via=via)
            found[resource_id] = cand
        elif cand.via == "burst" and via != "burst":
            cand.via = via                      # a stronger route wins
        if not cand.system_id:
            cand.system_id = system_for(resource_id) or system_id
        return cand


def _number(activity: Activity) -> int:
    """The numeric part of an activity id. Runs are contiguous in this number."""
    return int(activity.activity_id.split("_")[1])


def _tokens(text: str) -> set[str]:
    """Normalised words from an activity `details` field, for exact identifier lookup."""
    return {norm(t.strip(" .,;()")) for t in text.split() if t.strip(" .,;()")}
