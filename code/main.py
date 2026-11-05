"""Deletion audit agent — entry point.

    python code/main.py                 audit all 518 requests, write output.csv
    python code/main.py --samples       audit the 32 labelled cases and score them
    python code/main.py --case case_11  audit one case and print its plan

Writes `output.csv` at the repository root, one row per request, in the numeric case
order the input file uses. Lexicographic order would put `case_100` before `case_33`.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from audit import (dataset, engine, evidence, health, identity, intent,  # noqa: E402
                   inventory, llm, policy, vision)

COLUMNS = ("case_id", "deletion_status", "steps_json")


def build(data: dataset.Dataset, *, use_burst: bool = True,
          classify_intent: bool = True, read_images: bool = True) -> engine.Auditor:
    index = identity.IdentityIndex(data)
    reader = evidence.EvidenceReader(data)
    reader.read_all()

    client = None
    if classify_intent or read_images:
        try:
            client = llm.Client()
        except llm.LLMError as why:
            print(f"no model provider: {why}")

    if read_images and client is not None:
        seer = vision.VisionReader(client)
        added = reader.read_images(seer)
        print(f"vision pass: {added} observations from the screenshots"
              + (f"; {len(seer.failures)} unreadable" if seer.failures else ""))
        for file_id, why in seer.failures:
            print(f"   {file_id}: {why[:140]}")

    inv = inventory.Inventory(data, reader, use_burst=use_burst)

    classifier = None
    if classify_intent:
        try:
            classifier = intent.IntentClassifier(client or llm.Client())
        except llm.LLMError as why:
            # Running without a provider is allowed and produces a complete output.csv;
            # it just cannot find the non-deletion requests. Say so, rather than letting
            # a silent default look like a judgement.
            print(f"intent classification disabled: {why}")
            classifier = intent.IntentClassifier(None)

    auditor = engine.Auditor(data, index, reader, inv, policy.Policy(data),
                             authorizes_deletion=(classifier.authorises
                                                  if classifier else None))
    auditor.classifier = classifier
    return auditor


def write_output(path: Path, verdicts: list[engine.Verdict]) -> None:
    """Write the submission CSV.

    `newline=""` matters on Windows: without it the csv module's own \\r\\n is doubled
    and every second line of the file is blank. The file is plain UTF-8 without a BOM,
    because the grader parses it rather than opening it in a spreadsheet.
    """
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for v in verdicts:
            writer.writerow([v.case_id, v.status, json.dumps(v.steps,
                                                             ensure_ascii=False,
                                                             separators=(",", ":"))])


def check_output(path: Path, expected: int) -> None:
    """Read back what we wrote and verify it against the contract, before submitting.

    Checking the file instead of the objects in memory is deliberate: the failure modes
    that matter here are serialisation failures, and they are invisible from the inside.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    problems = []
    if len(rows) != expected:
        problems.append(f"{len(rows)} rows, expected {expected}")
    if rows and list(rows[0]) != list(COLUMNS):
        problems.append(f"columns are {list(rows[0])}")
    numbers = [int(r["case_id"].split("_")[1]) for r in rows]
    if numbers != sorted(numbers):
        problems.append("rows are not in case order")
    for r in rows:
        if r["deletion_status"] not in (engine.COMPLETE, engine.INCOMPLETE,
                                        engine.NOT_APPLICABLE):
            problems.append(f"{r['case_id']}: bad status {r['deletion_status']!r}")
        try:
            steps = json.loads(r["steps_json"])
        except json.JSONDecodeError as why:
            problems.append(f"{r['case_id']}: steps_json is not JSON ({why})")
            continue
        if r["deletion_status"] == engine.NOT_APPLICABLE and steps != []:
            problems.append(f"{r['case_id']}: NOT_APPLICABLE must carry []")
        if [s["step_no"] for s in steps] != list(range(1, len(steps) + 1)):
            problems.append(f"{r['case_id']}: step numbers are not 1..n")
    if problems:
        raise SystemExit("output.csv fails the contract:\n  "
                         + "\n  ".join(problems[:20]))
    print(f"output.csv passes the contract: {len(rows)} rows, columns {list(COLUMNS)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true",
                    help="audit the 32 labelled cases and score them")
    ap.add_argument("--case", default=None, help="audit one case and print its plan")
    ap.add_argument("--out", default=None, help="where to write output.csv")
    ap.add_argument("--no-burst", action="store_true",
                    help="attribute resources from evidence only, ignoring deletion runs")
    ap.add_argument("--no-intent", action="store_true",
                    help="skip intent classification")
    ap.add_argument("--no-vision", action="store_true",
                    help="skip the screenshot pass")
    ap.add_argument("--health", nargs="?", const="run_health.json", default=None,
                    help="write run health signals as JSON and exit non-zero on alert")
    args = ap.parse_args()

    started = time.perf_counter()
    data = dataset.load()
    auditor = build(data, use_burst=not args.no_burst,
                    classify_intent=not args.no_intent,
                    read_images=not args.no_vision)
    print(f"loaded in {time.perf_counter() - started:.1f}s: "
          f"{len(data.requests)} requests, "
          f"{auditor.reader.stats()['observations']} observations, "
          f"{len(auditor.reader.coverage)} coverage records")

    if args.samples:
        from audit import scoring
        requests, gold = dataset.load_samples()
        if auditor.classifier:
            auditor.classifier.warm([r.request_text for r in requests])
        verdicts = [auditor.audit(r) for r in requests]
        predicted = {v.case_id: (v.status, v.steps) for v in verdicts}
        report = scoring.score(predicted, gold)
        print("\n" + report.summary())
        print("\n" + scoring.confusion_table(report))
        print(f"\nweakest cases: {report.worst_cases(8)}")
        notes = [n for v in verdicts for n in v.notes]
        print(f"\n{len(notes)} unresolved notes; most common:")
        import collections
        kinds = collections.Counter(n.split(": ", 1)[-1] for n in notes)
        for kind, count in kinds.most_common(6):
            print(f"   {count:4}  {kind}")
        return 0

    if args.case:
        request = next(r for r in data.requests if r.case_id == args.case)
        verdict = auditor.audit(request)
        print(f"\n{verdict.case_id}: {verdict.status}")
        for s in verdict.steps:
            print(f"  {s['step_no']:3} {s['phase']:13} {s['operation']:26} "
                  f"{s['system_id']:20} {s['resource_id']:20} {s['state']:11} "
                  f"{s['evidence_id'] or '-'}")
        for n in verdict.notes:
            print(f"  note: {n}")
        return 0

    if auditor.classifier:
        # Classify every message first, in batches. One at a time this is 375 round
        # trips; batched it is about fifteen, and it also enables the second pass that
        # confirms each refusal individually.
        auditor.classifier.warm([r.request_text for r in data.requests])
    verdicts = [auditor.audit(r) for r in data.requests]
    out = Path(args.out) if args.out else dataset.repo_root() / "output.csv"
    write_output(out, verdicts)
    check_output(out, len(data.requests))

    import collections
    counts = collections.Counter(v.status for v in verdicts)
    print(f"wrote {out}")
    print(f"statuses: {dict(counts)}")
    print(f"total steps: {sum(len(v.steps) for v in verdicts)}")
    print(f"elapsed: {time.perf_counter() - started:.1f}s")
    if auditor.classifier and auditor.classifier.client:
        print(f"model usage: {auditor.classifier.client.usage.summary()}")
        if auditor.classifier.errors:
            print(f"classification failures: {len(auditor.classifier.errors)}; "
                  f"first: {auditor.classifier.errors[0][:120]}")
    if auditor.classifier and auditor.classifier.attacks:
        print(f"prompt-injection markers in {len(auditor.classifier.attacks)} "
              f"message(s); each refusal from one was rejected")

    signals = health.measure(verdicts, auditor.reader, auditor.classifier,
                             data.requests)
    if args.health:
        destination = Path(args.health)
        signals.write(destination)
        print(f"\nrun health -> {destination}")
        print(signals.report())
        if signals.breaches:
            print(f"\n{len(signals.breaches)} signal(s) outside their threshold: "
                  + ", ".join(s.name for s in signals.breaches))
            return 3
    elif signals.breaches:
        print(f"run health: {len(signals.breaches)} signal(s) outside their "
              f"threshold ({', '.join(s.name for s in signals.breaches)}); "
              "run with --health for the detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
