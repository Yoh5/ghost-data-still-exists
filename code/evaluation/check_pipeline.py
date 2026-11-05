"""Measure the stages that exist, before building the ones that do not.

    python code/evaluation/check_pipeline.py

Three questions, in order of how much they would cost to discover late:

  identity   can every case's email be resolved to exactly one subject?
  retrieval  of the resources the official answers name, how many do we even find?
             This is the ceiling on every later metric: a resource we never see cannot
             be judged, remediated or verified, however good the policy logic is.
  grounding  does sample case_11 reproduce? Its findings cite evidence_03, the shift
             handover, which states account_4248 as NOT_FOUND for novak.tomasz@icloud.com.
             If that link breaks, retrieval is broken, whatever the aggregate says.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from audit import dataset, evidence, identity  # noqa: E402


def main() -> int:
    data = dataset.load()
    index = identity.IdentityIndex(data)
    print(f"dataset: {len(data.requests)} cases, {len(index)} subjects, "
          f"{index.identifier_count} distinct identifiers "
          f"({index.identifier_count - len(index) * 4} more than one per field, "
          "i.e. historical)")

    # -- identity ------------------------------------------------------------------ #
    failed = []
    historical = 0
    for request in data.requests:
        try:
            subject = index.resolve(request.email)
        except identity.IdentityError as why:
            failed.append((request.case_id, str(why)))
            continue
        current = next((i.email for i in data.identities
                        if i.user_id == subject.user_id), "")
        if identity.norm(request.email) != identity.norm(current):
            historical += 1
    print(f"\n[identity]  resolved {len(data.requests) - len(failed)}/"
          f"{len(data.requests)} case emails")
    print(f"            {historical} cases arrive with a HISTORICAL email, not the "
          "current one")
    for case_id, why in failed[:5]:
        print(f"            unresolved {case_id}: {why}")

    # -- evidence ------------------------------------------------------------------ #
    reader = evidence.EvidenceReader(data)
    reader.read_all()
    stats = reader.stats()
    print(f"\n[evidence]  {stats['observations']} observations from "
          f"{len(data.evidence) - stats['files_unread']} files; "
          f"{stats['files_unread']} unread")
    for name, count in stats["by_reader"].items():
        print(f"            {name:22} {count:6}")
    reasons = collections.Counter(why.split(" (")[0].split(":")[0]
                                 for _, why in reader.unread)
    print(f"            unread reasons: {dict(reasons)}")
    by_id = data.evidence_by_id()
    silent = [(fid, why) for fid, why in reader.unread
              if "multimodal" not in why]
    if silent:
        print("            files that are text but yielded nothing:")
        for fid, why in silent:
            print(f"              {fid:12} {Path(by_id[fid].file_path).name:52} {why}")

    # -- grounding: sample case_11 ------------------------------------------------- #
    print("\n[grounding] sample case_11, via the shift handover")
    subject = index.resolve("novak.tomasz@icloud.com")
    seen = reader.for_identifiers(subject.identifiers)
    handover = [o for o in seen if o.resource_id == "account_4248"]
    print(f"            subject {subject.user_id}, "
          f"{len(subject.identifiers)} identifiers, {len(seen)} observations")
    for o in handover:
        print(f"            {o.file_id} {o.reader:12} {o.system_id:18} "
              f"{o.resource_id:14} present={o.present} {o.flags.get('state', '')}")
    grounded = any(o.file_id == "evidence_03" and o.present is False
                   for o in handover)
    print(f"            account_4248 proven ABSENT by evidence_03: {grounded}")

    # -- retrieval ceiling --------------------------------------------------------- #
    sample_requests, gold = dataset.load_samples()
    print("\n[retrieval] can we see the resources the official answers name?")
    found_total = missed_total = 0
    per_system_missed: collections.Counter = collections.Counter()
    worst: list[tuple[str, int, int]] = []
    for request in sample_requests:
        status, steps = gold[request.case_id]
        wanted = {(s["system_id"], s["resource_id"]) for s in steps}
        if not wanted:
            continue
        try:
            subject = index.resolve(request.email)
        except identity.IdentityError:
            missed_total += len(wanted)
            worst.append((request.case_id, 0, len(wanted)))
            continue
        seen = reader.for_identifiers(subject.identifiers,
                                      not_after=request.audit_at)
        have = {(o.system_id, o.resource_id) for o in seen}
        # A resource also counts as seen when any observation names it, whatever system
        # the evidence attributed it to: the system is recoverable from the prefix.
        have |= {(evidence.system_for(o.resource_id) or o.system_id, o.resource_id)
                 for o in seen}
        hit = wanted & have
        miss = wanted - have
        found_total += len(hit)
        missed_total += len(miss)
        for system, _ in miss:
            per_system_missed[system] += 1
        if miss:
            worst.append((request.case_id, len(hit), len(wanted)))

    total = found_total + missed_total
    print(f"            recall on named resources: {found_total}/{total} "
          f"= {found_total / total:.3f}")
    print(f"            missed by system: {dict(per_system_missed.most_common())}")
    print(f"            weakest cases: "
          f"{[f'{c} {h}/{w}' for c, h, w in sorted(worst, key=lambda x: x[1] / x[2])[:8]]}")

    print("\nnext: the resources still missing come from the families with no reader "
          "yet (images, PDFs) and from observations whose subject link is indirect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
