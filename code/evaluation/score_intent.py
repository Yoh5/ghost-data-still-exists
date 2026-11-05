"""Measure intent classification on all 518 requests.

    python code/evaluation/score_intent.py

There are no published labels for this: none of the 32 sample answers is
`NOT_APPLICABLE`. So the measurement is built from three independent views, and the
report states where each number comes from rather than presenting one as truth.

  reference   the 518 request texts group into 27 distinct openings; the non-deletion
              ones are the templates that appear exactly once. Derived from the text,
              never from a case id.
  baseline    the keyword filter, to show what it costs rather than assert it.
  corroboration  system_activity.csv holds exactly 10 CLASSIFY_REQUEST rows reading
              "Privacy intake classified request for <account> as non-deletion". Those
              are a workflow CLAIM -- the thing this whole problem is about not trusting
              -- so they are used to check the classifier, never to decide a case.
"""
from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from audit import dataset, intent, llm  # noqa: E402


def reference_set(requests) -> set[str]:
    """Cases whose opening sentence is unique in the corpus."""
    first = lambda t: re.split(r"(?<=[.!?])\s+", t.strip())[0]
    counts = collections.Counter(first(r.request_text) for r in requests)
    return {r.case_id for r in requests if counts[first(r.request_text)] == 1}


def main() -> int:
    data = dataset.load()
    requests = data.requests
    reference = reference_set(requests)
    print(f"{len(requests)} requests; {len(set(' '.join(r.request_text.split()) for r in requests))} "
          f"distinct texts; reference non-deletion set: {len(reference)} cases "
          f"({', '.join(sorted(reference, key=lambda c: int(c.split('_')[1]))[:4])}...)")

    baseline = intent.KeywordBaseline()
    keyword_na = {r.case_id for r in requests
                  if not baseline.classify(r.request_text).authorises}
    _report("keyword baseline", keyword_na, reference)
    wrong = sorted(reference - keyword_na, key=lambda c: int(c.split("_")[1]))
    print(f"   the keyword filter calls these deletion requests, and they are not: {wrong}")
    for case_id in wrong[:3]:
        text = next(r.request_text for r in requests if r.case_id == case_id)
        print(f"     {case_id}: {text[:110]}")

    try:
        client = llm.Client()
    except llm.LLMError as why:
        print(f"\nno provider configured, model classification skipped: {why}")
        return 0

    print(f"\nprovider {client.provider}, model {client.model}")
    classifier = intent.IntentClassifier(client)
    classifier.warm([r.request_text for r in requests])
    model_na, actions = set(), {}
    for request in requests:
        result = classifier.classify(request.request_text)
        if not result.authorises:
            model_na.add(request.case_id)
            actions[request.case_id] = result.action
    _report("model classifier", model_na, reference)
    for case_id in sorted(model_na, key=lambda c: int(c.split("_")[1])):
        print(f"     {case_id}: {actions.get(case_id, '')}")
    print(f"   usage: {client.usage.summary()}")
    print(f"   calls per case: {client.usage.calls / len(requests):.3f} "
          f"(caching on the message text, not the case id)")
    if classifier.errors:
        print(f"   {len(classifier.errors)} classification failures, counted as "
              f"deletion requests and recorded")

    # Corroboration, not ground truth.
    accounts = {a.resource_id for a in data.activity
                if a.event_type == "CLASSIFY_REQUEST"}
    print(f"\ncorroboration: system_activity.csv claims {len(accounts)} non-deletion "
          f"requests; the classifier found {len(model_na)}")
    print("   those rows are a workflow claim and are not used to decide any case")
    return 0


def _report(name: str, found: set[str], reference: set[str]) -> None:
    tp = len(found & reference)
    fp = len(found - reference)
    fn = len(reference - found)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    print(f"\n{name}: found {len(found)} non-deletion cases; "
          f"P{precision:.3f} R{recall:.3f} F1 {f1:.3f} "
          f"(agreed {tp}, extra {fp}, missed {fn})")


if __name__ == "__main__":
    raise SystemExit(main())
