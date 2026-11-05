"""Score a predictor against the 32 public answers, and self-test the harness.

    python code/evaluation/score_samples.py

Run with no predictor it checks the measuring instrument itself, which has to happen
before the instrument is trusted to judge anything:

  order        does our serialiser reproduce the official step order, case for case?
  oracle       does the scorer report a perfect 1.0 when fed the answers as predictions?
  shuffled     does it separate "right steps, wrong order" from "wrong steps"?
  baselines    what do trivial strategies score, so later gains can be read against them?

A scorer that cannot fail is not a scorer.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from audit import dataset, scoring, steps  # noqa: E402


def check_order_is_mechanical(gold: dict) -> tuple[int, int, list[str]]:
    """Measurement M1: re-derive each official step array from its own steps.

    Parse the published steps, throw their order away, re-order them with our rule, and
    require the result to be identical. If this passes on every case, ordering and
    numbering are solved for good and no later change can quietly break them.
    """
    ok, total, failures = 0, 0, []
    for case_id, (_, gold_steps) in sorted(gold.items()):
        total += 1
        shuffled = list(gold_steps)
        random.Random(0).shuffle(shuffled)
        rebuilt = steps.serialise(steps.parse(shuffled))
        if rebuilt == gold_steps:
            ok += 1
        else:
            failures.append(case_id)
    return ok, total, failures


def main() -> int:
    requests, gold = dataset.load_samples()
    print(f"loaded {len(requests)} sample requests with answers\n")

    ok, total, failures = check_order_is_mechanical(gold)
    print(f"[order]   serialiser reproduces the official order: {ok}/{total}")
    if failures:
        print(f"          FAILED on {failures}")
        print("          ordering is not mechanical after all; PLAN.md M1 is wrong")
    print()

    oracle = {c: (s, st) for c, (s, st) in gold.items()}
    rep = scoring.score(oracle, gold)
    print("[oracle]  ", rep.summary())
    perfect = (rep.status_accuracy == rep.sequence_accuracy == rep.step_f1
               == rep.field_accuracy == rep.evidence_accuracy == 1.0)
    print(f"           scorer reports a perfect run on the answers: {perfect}")
    if not perfect:
        print("           the scorer is broken; fix it before trusting any other number")
    print()

    rng = random.Random(1)
    shuffled = {}
    for c, (s, st) in gold.items():
        order = list(st)
        rng.shuffle(order)
        shuffled[c] = (s, order)
    rep_shuf = scoring.score(shuffled, gold)
    print("[shuffled]", rep_shuf.summary())
    print(f"           step F1 unchanged ({rep_shuf.step_f1:.3f}), "
          f"sequence collapsed ({rep_shuf.sequence_accuracy:.3f}): "
          "the two metrics measure different things")
    print()

    print("--- baselines, so later gains can be read against something ---")
    for name, make in (
        ("everything INCOMPLETE, no steps", lambda r: ("INCOMPLETE", [])),
        ("everything COMPLETE, no steps", lambda r: ("COMPLETE", [])),
        ("trust reported_status", lambda r: (
            {"COMPLETE": "COMPLETE", "PARTIALLY_COMPLETE": "INCOMPLETE",
             "NOT_STARTED": "INCOMPLETE"}[r.reported_status], [])),
    ):
        pred = {r.case_id: make(r) for r in requests}
        rep_b = scoring.score(pred, gold)
        print(f"  {name:34} status {rep_b.status_accuracy:.3f}")

    print()
    print("distribution of the answers:")
    counts: dict[str, int] = {}
    for _, (s, _) in gold.items():
        counts[s] = counts.get(s, 0) + 1
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("  NOT_APPLICABLE has no example in the public set; three of our own "
          "evaluation cases must cover it")

    return 0 if (not failures and perfect) else 1


if __name__ == "__main__":
    raise SystemExit(main())
