"""What an operator would watch if this ran every night.

An audit agent fails quietly. It does not crash when it starts missing copies of
someone's data: it returns COMPLETE, the dashboard turns green, and the failure is
discovered when a deleted customer tries to sign up again. That is the whole story in the
problem statement, and it is a monitoring failure as much as an engineering one.

So the run emits the handful of signals that would actually catch it, with thresholds
attached. The most important one is counter-intuitive: **a rise in COMPLETE verdicts is
the alarm.** An agent that quietly stops finding records reports better results, not
worse. Anything measuring "errors" would stay silent through exactly the failure this
system exists to prevent.

    python code/main.py --health run_health.json

Writes a flat JSON document, one line per signal, meant to be scraped rather than read.
A breached threshold sets the process exit code, so a scheduler notices without anyone
reading anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class Signal:
    name: str
    value: float
    #: None means "report it, do not alert on it"
    limit: float | None = None
    direction: str = "max"          # "max": alert above the limit; "min": below
    note: str = ""

    @property
    def breached(self) -> bool:
        if self.limit is None:
            return False
        return (self.value > self.limit if self.direction == "max"
                else self.value < self.limit)


@dataclass(slots=True)
class Health:
    signals: list[Signal] = field(default_factory=list)

    def add(self, name: str, value: float, *, limit: float | None = None,
            direction: str = "max", note: str = "") -> None:
        self.signals.append(Signal(name, value, limit, direction, note))

    @property
    def breaches(self) -> list[Signal]:
        return [s for s in self.signals if s.breached]

    def as_dict(self) -> dict:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "healthy": not self.breaches,
            "signals": {s.name: {"value": s.value, "limit": s.limit,
                                 "breached": s.breached, "note": s.note}
                        for s in self.signals},
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")

    def report(self) -> str:
        lines = [f"{'signal':34} {'value':>10} {'limit':>10}  "]
        for s in self.signals:
            mark = "  ALERT" if s.breached else ""
            limit = "—" if s.limit is None else f"{s.limit:g}"
            lines.append(f"{s.name:34} {s.value:>10.4g} {limit:>10}{mark}")
            if s.note:
                lines.append(f"{'':34} {s.note}")
        return "\n".join(lines)


def measure(verdicts, reader, classifier, requests) -> Health:
    """Build the signals from a finished run."""
    health = Health()
    n = max(len(verdicts), 1)

    complete = sum(1 for v in verdicts if v.status == "COMPLETE")
    not_applicable = sum(1 for v in verdicts if v.status == "NOT_APPLICABLE")
    blocked = sum(1 for v in verdicts
                  if any("state not established" in note for note in v.notes))
    no_steps = sum(1 for v in verdicts
                   if v.status != "NOT_APPLICABLE" and not v.steps)

    # The signal that matters most, and the one a naive dashboard would never have.
    health.add("complete_rate", complete / n, limit=0.60,
               note="a rise here is the alarm: an agent that stops finding records "
                    "reports better results, not worse")
    health.add("not_applicable_rate", not_applicable / n, limit=0.10,
               note="a rise means requests are being dismissed without an audit")
    health.add("cases_with_no_plan", no_steps / n, limit=0.10,
               note="an authorised deletion we had nothing to say about")
    health.add("cases_blocked_by_unknown_state", blocked / n, limit=0.25,
               note="copies we could not establish the state of; these are the ones "
                    "that become ghosts")

    health.add("evidence_files_unread", len(reader.unread), limit=0,
               note="; ".join(f"{f}: {why}" for f, why in reader.unread[:4])
                    or "every file was read")
    health.add("evidence_files_read_but_empty", len(getattr(reader, "accounted", [])),
               note="; ".join(f"{f}: {why}" for f, why in
                              getattr(reader, "accounted", [])[:3]))
    health.add("evidence_observations", len(reader.observations), limit=1000,
               direction="min", note="a sudden fall means a format changed under us")
    health.add("evidence_coverage_records", len(reader.coverage))

    unresolved = sum(1 for v in verdicts
                     if any("identity unresolved" in note for note in v.notes))
    health.add("identities_unresolved", unresolved, limit=0,
               note="a request we could not attach to a person")

    if classifier is not None:
        health.add("intent_classification_failures", len(classifier.errors), limit=0)
        health.add("prompt_injection_attempts", len(classifier.attacks), limit=0,
                   note="; ".join(why for _, why in classifier.attacks[:3])
                        or "none seen in this run")
        if classifier.client is not None:
            usage = classifier.client.usage
            health.add("model_calls", usage.calls)
            health.add("model_call_failures", usage.failures, limit=0)
            health.add("cost_usd", round(usage.cost_usd, 4), limit=1.0,
                       note="a run that suddenly costs more is a run doing "
                            "something different")
            health.add("model_calls_per_case", round(usage.calls / n, 4), limit=1.0)

    health.add("requests_processed", len(requests), limit=len(requests),
               direction="min")
    return health
