"""Scoring against known answers: the four metrics the evaluation report must contain.

This module exists before any predictor does. Nothing in this solution is improved on a
hunch: a change is kept only if it moves a number here.

The metrics follow problem_statement.md's Evaluation section:

  status accuracy    one point per case, exact match on deletion_status
  step accuracy      precision / recall / F1 over step identities, order ignored
  field accuracy     per-field agreement on positionally aligned steps
  sequence accuracy  one point per case whose step array matches position for position

Step identity is (phase, operation, system_id, resource_id, state). `evidence_id` is
scored on its own, because citing the wrong file is a different failure from finding the
wrong record, and averaging the two would hide both.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field

SCORED_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")


def identity(step: dict) -> tuple:
    return (step["phase"], step["operation"], step["system_id"], step["resource_id"],
            step["state"])


@dataclass
class Report:
    n_cases: int = 0
    status_correct: int = 0
    sequence_correct: int = 0

    step_tp: int = 0                 # predicted steps that exist in the answer
    step_fp: int = 0                 # predicted steps that do not
    step_fn: int = 0                 # answer steps we failed to predict

    field_correct: int = 0
    field_total: int = 0
    evidence_correct: int = 0
    evidence_total: int = 0

    confusion: collections.Counter = field(default_factory=collections.Counter)
    per_case: dict[str, dict] = field(default_factory=dict)

    @property
    def status_accuracy(self) -> float:
        return self.status_correct / self.n_cases if self.n_cases else 0.0

    @property
    def sequence_accuracy(self) -> float:
        return self.sequence_correct / self.n_cases if self.n_cases else 0.0

    @property
    def step_precision(self) -> float:
        d = self.step_tp + self.step_fp
        return self.step_tp / d if d else 0.0

    @property
    def step_recall(self) -> float:
        d = self.step_tp + self.step_fn
        return self.step_tp / d if d else 0.0

    @property
    def step_f1(self) -> float:
        p, r = self.step_precision, self.step_recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def field_accuracy(self) -> float:
        return self.field_correct / self.field_total if self.field_total else 0.0

    @property
    def evidence_accuracy(self) -> float:
        return self.evidence_correct / self.evidence_total if self.evidence_total else 0.0

    def worst_cases(self, n: int = 10) -> list[str]:
        """Cases to look at first: wrong status before wrong steps."""
        ranked = sorted(self.per_case.items(),
                        key=lambda kv: (kv[1]["status_ok"], kv[1]["step_f1"]))
        return [c for c, _ in ranked[:n]]

    def summary(self) -> str:
        return (f"n={self.n_cases}  status {self.status_accuracy:.3f}  "
                f"sequence {self.sequence_accuracy:.3f}  "
                f"steps P{self.step_precision:.3f}/R{self.step_recall:.3f}/"
                f"F1 {self.step_f1:.3f}  fields {self.field_accuracy:.3f}  "
                f"evidence {self.evidence_accuracy:.3f}")


def score(predicted: dict[str, tuple[str, list[dict]]],
          gold: dict[str, tuple[str, list[dict]]]) -> Report:
    """Compare predictions with answers.

    A case present in `gold` but missing from `predicted` is scored as a total miss, not
    skipped. Silently dropping the cases we could not answer would make every metric
    flatter and would be the exact failure this whole solution is about.
    """
    rep = Report()

    for case_id, (gold_status, gold_steps) in gold.items():
        rep.n_cases += 1
        pred_status, pred_steps = predicted.get(case_id, ("<missing>", []))

        status_ok = pred_status == gold_status
        rep.status_correct += status_ok
        rep.confusion[(gold_status, pred_status)] += 1

        gold_ids = collections.Counter(identity(s) for s in gold_steps)
        pred_ids = collections.Counter(identity(s) for s in pred_steps)
        tp = sum((gold_ids & pred_ids).values())
        rep.step_tp += tp
        rep.step_fp += sum(pred_ids.values()) - tp
        rep.step_fn += sum(gold_ids.values()) - tp

        sequence_ok = ([identity(s) for s in gold_steps]
                       == [identity(s) for s in pred_steps])
        rep.sequence_correct += sequence_ok

        # Field agreement on positionally aligned steps. Unaligned gold steps count as
        # wrong on every field, so a short plan is penalised rather than ignored.
        for i, g in enumerate(gold_steps):
            p = pred_steps[i] if i < len(pred_steps) else {}
            for f in SCORED_FIELDS:
                rep.field_total += 1
                rep.field_correct += p.get(f) == g.get(f)
            if g.get("evidence_id"):
                rep.evidence_total += 1
                rep.evidence_correct += p.get("evidence_id") == g.get("evidence_id")

        case_tp = tp
        case_p = case_tp / max(sum(pred_ids.values()), 1)
        case_r = case_tp / max(sum(gold_ids.values()), 1)
        rep.per_case[case_id] = {
            "status_ok": status_ok,
            "gold_status": gold_status,
            "pred_status": pred_status,
            "n_gold": len(gold_steps),
            "n_pred": len(pred_steps),
            "sequence_ok": sequence_ok,
            "step_f1": 2 * case_p * case_r / (case_p + case_r) if case_p + case_r else 0.0,
            "missing": [list(k) for k in (gold_ids - pred_ids)],
            "spurious": [list(k) for k in (pred_ids - gold_ids)],
        }

    return rep


def confusion_table(rep: Report) -> str:
    labels = sorted({g for g, _ in rep.confusion} | {p for _, p in rep.confusion})
    width = max(len(l) for l in labels) + 2
    head = "gold \\ pred".ljust(16) + "".join(l.ljust(width) for l in labels)
    lines = [head]
    for g in labels:
        row = g.ljust(16)
        for p in labels:
            row += str(rep.confusion.get((g, p), 0)).ljust(width)
        lines.append(row)
    return "\n".join(lines)
