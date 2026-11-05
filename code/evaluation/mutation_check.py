"""Do the tests actually catch anything?

    python code/evaluation/mutation_check.py

A green test suite proves the tests ran, not that they would notice if the code broke.
So this deliberately breaks the code, one fault at a time, and checks that the suite goes
red. Each fault is a real mistake someone could make here -- several are mistakes that
were actually made and fixed during the build.

A fault nothing catches is a gap in the tests, named rather than left unknown.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from audit import engine, evidence, identity, intent, inventory, policy, steps  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def patched(target, attribute, value):
    original = getattr(target, attribute)
    setattr(target, attribute, value)
    try:
        yield
    finally:
        setattr(target, attribute, original)


# --------------------------------------------------------------------------------- #
# The faults
# --------------------------------------------------------------------------------- #

def order_by_resource_only():
    """Sort steps by resource id, ignoring the phase and operation order."""
    return patched(steps.Step, "sort_key",
                   property(lambda self: (self.resource_id,)))


def number_steps_from_zero():
    original = steps.serialise

    def broken(found):
        out = original(found)
        for s in out:
            s["step_no"] -= 1
        return out
    return patched(steps, "serialise", broken)


def match_identifiers_by_substring():
    """Drop the token boundary when scanning text for an identifier.

    The first version of this fault patched `Subject.matches`, and nothing caught it --
    correctly, because that is not where the risk lives. Full addresses do not nest
    inside one another; what nests is an address inside a longer surrounding token. The
    fault had to be made faithful before the result meant anything.
    """
    def loose(self, text):
        hay = identity.norm(text)
        return {ident for ident in self.identifiers if ident and ident in hay}
    return patched(identity.Subject, "mentioned_in", loose)


@contextlib.contextmanager
def patched_state(broken):
    """Replace `observed_state` everywhere it is bound, not only on its own module.

    `engine.py` does `from .policy import observed_state`, so it holds its own reference
    and patching `policy.observed_state` alone leaves the engine untouched. One fault was
    silently ineffective because of exactly that, and the harness still reported it as
    caught -- by failures leaking in from the previous fault in the same process. A
    mutation harness that lies is worse than none, because it certifies the tests.
    """
    with patched(policy, "observed_state", broken), \
            patched(engine, "observed_state", broken):
        yield


def treat_unknown_as_absent():
    """The ghost itself: nobody looked, so it must be gone."""
    original = policy.observed_state

    def broken(candidate, category):
        state, proof = original(candidate, category)
        return (policy.ABSENT if state == policy.UNKNOWN else state), proof
    return patched_state(broken)


def let_a_log_line_prove_redaction():
    """Absence of an email in a log read as absence of an email in the record."""
    return patched(evidence.Observation, "field_level", property(lambda self: True))


def trust_the_workflow_claim():
    """Answer from `reported_status` instead of from the evidence."""
    original = engine.Auditor.audit

    def broken(self, request):
        verdict = original(self, request)
        if verdict.status != engine.NOT_APPLICABLE:
            verdict.status = (engine.COMPLETE
                              if request.reported_status == "COMPLETE"
                              else engine.INCOMPLETE)
        return verdict
    return patched(engine.Auditor, "audit", broken)


def ignore_the_audit_cutoff():
    """Let a case see, and cite, evidence captured after its own cutoff.

    Patching only the identifier query left the cutoff standing, because the inventory
    filters observations again when it attaches them. The fault has to remove it where
    the citations actually come from.
    """
    original = inventory.Inventory.resources_for

    def broken(self, subject, audit_at):
        far_future = audit_at.replace(year=audit_at.year + 50)
        return original(self, subject, far_future)
    return patched(inventory.Inventory, "resources_for", broken)


def cite_evidence_on_future_work():
    """Pretend a step that has not happened yet is already proven."""
    original = engine.Auditor.audit

    def broken(self, request):
        verdict = original(self, request)
        for step in verdict.steps:
            if not step["evidence_id"]:
                step["evidence_id"] = "evidence_01"
        return verdict
    return patched(engine.Auditor, "audit", broken)


def accept_an_injected_refusal():
    """Drop the guard that stops an injection suppressing an audit."""
    return patched(intent.IntentClassifier, "_refuse_suppression",
                   staticmethod(lambda result: result))


def drop_the_one_per_system_rule():
    original = inventory.Inventory.__init__

    def broken(self, *args, **kwargs):
        kwargs["one_per_system"] = False
        original(self, *args, **kwargs)
    return patched(inventory.Inventory, "__init__", broken)


def answer_from_the_case_id():
    """The forbidden shortcut: branch on which case this is."""
    original = engine.Auditor.audit

    def broken(self, request):
        verdict = original(self, request)
        if request.case_number % 2 == 0:
            verdict.status = engine.COMPLETE
            verdict.steps = []
        return verdict
    return patched(engine.Auditor, "audit", broken)


def let_a_null_count_as_an_identifier():
    """Index the literal string "null", tying every redacted record to one ghost."""
    original = evidence.Observation.add_subject

    def broken(self, *values):
        for value in values:
            if value:
                self.subject_keys.add(evidence.norm(str(value)))
    return patched(evidence.Observation, "add_subject", broken)


def treat_an_unknown_backup_as_compliant():
    """Let an archive nobody checked pass as blocked."""
    original = policy.observed_state

    def broken(candidate, category):
        state, proof = original(candidate, category)
        if category == "BACKUP_ARCHIVE" and state == policy.UNKNOWN:
            return policy.BLOCKED, proof
        return state, proof
    return patched_state(broken)


def use_the_latest_observation_even_if_it_says_nothing():
    """Let a later, silent observation bury an earlier one that settled the state."""
    original = policy.observed_state

    def broken(candidate, category):
        newest = candidate.latest_observation()
        if newest is None:
            return policy.UNKNOWN, None
        cut = type(candidate)(resource_id=candidate.resource_id,
                              system_id=candidate.system_id, via=candidate.via)
        cut.observations = [newest]
        cut.activities = candidate.activities
        return original(cut, category)
    return patched_state(broken)


def let_a_screenshot_invent_a_resource():
    """Accept any identifier a vision model returns, whatever family it claims."""
    return patched(evidence, "system_for", lambda rid: "account_service")


def let_an_injection_through_unnoticed():
    """Stop recognising injection markers, so a refusal from one is accepted."""
    from audit import untrusted

    def blind(raw):
        return untrusted.Clean(text=" ".join((raw or "").split()),
                               suspicions=[], truncated=False)
    return patched(untrusted, "neutralise", blind)


def write_the_csv_without_newline_control():
    """On Windows this doubles the line ending and blanks every other row."""
    import csv as csv_module
    import json as json_module
    import main as agent

    def broken(path, verdicts):
        with path.open("w", encoding="utf-8") as handle:
            writer = csv_module.writer(handle)
            writer.writerow(agent.COLUMNS)
            for v in verdicts:
                writer.writerow([v.case_id, v.status,
                                 json_module.dumps(v.steps, ensure_ascii=False,
                                                   separators=(",", ":"))])
    return patched(agent, "write_output", broken)


def keep_duplicate_steps():
    """Emitting a step twice shifts every following step_no."""
    original = steps.serialise

    def broken(found):
        ordered = steps.order_steps(found)
        return [{"step_no": i, "phase": s.phase, "system_id": s.system_id,
                 "resource_id": s.resource_id, "operation": s.operation,
                 "state": s.state, "evidence_id": s.evidence_id}
                for i, s in enumerate(ordered, 1)]
    return patched(steps, "serialise", broken)


def resolve_an_ambiguous_identity_by_picking(self=None):
    """Pick the first owner instead of refusing, and audit the wrong person."""
    def loose(self, value):
        key = identity.norm(value)
        owners = self._by_identifier.get(key, set())
        if not owners:
            raise identity.IdentityError("no subject owns " + repr(value))
        return self._subjects[sorted(owners)[0]]
    return patched(identity.IdentityIndex, "resolve", loose)


def accept_a_misaligned_batch():
    """Zip the model's verdicts against the messages without checking the count."""
    original = intent.IntentClassifier.warm

    def broken(self, texts, *, batch_size=25):
        if self.client is None:
            return
        pending = []
        for text in texts:
            key = " ".join(text.split())
            if key not in self.seen and key not in pending:
                pending.append(key)
        for start in range(0, len(pending), batch_size):
            chunk = pending[start:start + batch_size]
            from audit import untrusted
            cleaned = [untrusted.neutralise(t) for t in chunk]
            numbered = chr(10).join(
                "[" + str(i + 1) + "]" + chr(10) + untrusted.fence(c.text)
                for i, c in enumerate(cleaned))
            try:
                answer = self.client.ask_json(intent.BATCH_SYSTEM, numbered,
                                              max_tokens=120 * len(chunk) + 200)
                for text, verdict in zip(chunk, answer.get("results") or []):
                    self.seen[text] = intent.Intent(
                        bool(verdict.get("authorises_deletion")), "", "", "model", [])
            except Exception:                                    # noqa: BLE001
                for text in chunk:
                    self.classify(text)
    return patched(intent.IntentClassifier, "warm", broken)


def let_a_scan_line_prove_redaction():
    """Treat a PII scan as a full field enumeration, so silence reads as redacted."""
    return patched(evidence.Observation, "field_level", property(lambda self: True))


def let_a_screenshot_recategorise_anything():
    """Allow a vision category to move a record out of its resource family."""
    original = policy.category_of

    def broken(candidate, observation):
        if observation is not None and observation.category:
            named = observation.category.strip().upper().replace(" ", "_")
            if named in policy.KNOWN_CATEGORIES:
                return named
        return original(candidate, observation)
    return patched(policy, "category_of", broken)


def remove_the_sql_authorizer():
    """Make the evidence-SQL guard permissive, so ATTACH can write a file.

    The first version of this fault patched `sqlite3.Connection.set_authorizer`, which
    does nothing: Connection is a C type and its methods cannot be replaced. The fault
    was inert and the harness reported it as uncaught -- correctly, which is the point of
    running each fault on its own.
    """
    import sqlite3

    def permissive(action, arg1, arg2, database, trigger):   # noqa: ARG001
        return sqlite3.SQLITE_OK
    return patched(evidence, "_confined", permissive)


FAULTS = [
    ("step order ignores phase and operation", order_by_resource_only),
    ("step numbers start at zero", number_steps_from_zero),
    ("identifiers match by substring", match_identifiers_by_substring),
    ("an unestablished state counts as absent", treat_unknown_as_absent),
    ("a log line may prove redaction", let_a_log_line_prove_redaction),
    ("the verdict comes from reported_status", trust_the_workflow_claim),
    ("the audit_at cutoff is ignored", ignore_the_audit_cutoff),
    ("future work cites evidence", cite_evidence_on_future_work),
    ("an injected refusal is accepted", accept_an_injected_refusal),
    ("several resources per system are kept", drop_the_one_per_system_rule),
    ("the answer depends on the case id", answer_from_the_case_id),
    ("a null value counts as an identifier", let_a_null_count_as_an_identifier),
    ("an unchecked backup passes as blocked", treat_an_unknown_backup_as_compliant),
    ("a later silent observation buries an earlier one",
     use_the_latest_observation_even_if_it_says_nothing),
    ("a screenshot may invent a resource family", let_a_screenshot_invent_a_resource),
    ("injection markers go unnoticed", let_an_injection_through_unnoticed),
    ("the CSV is written without newline control",
     write_the_csv_without_newline_control),
    ("duplicate steps are emitted", keep_duplicate_steps),
    ("an ambiguous identity is resolved by picking",
     resolve_an_ambiguous_identity_by_picking),
    ("a misaligned batch reply is accepted", accept_a_misaligned_batch),
    ("a PII scan counts as a field enumeration", let_a_scan_line_prove_redaction),
    ("a screenshot may recategorise a record", let_a_screenshot_recategorise_anything),
    ("evidence SQL runs unconfined", remove_the_sql_authorizer),
]


# --------------------------------------------------------------------------------- #

def run_suite() -> tuple[bool, list[str]]:
    """Run every test quietly. Returns (passed, names of failures)."""
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    names = [str(t).split(" ")[0] for t, _ in result.failures + result.errors]
    return result.wasSuccessful(), sorted(set(names))


def main() -> int:
    # One fault per process. Running them in sequence let a fault's effects survive into
    # the next one's run -- restoring an attribute does not undo what the tests cached
    # along the way -- and the count came out inflated. A subprocess each is slower and
    # true, which is the only version of this number worth printing.
    if len(sys.argv) > 1 and sys.argv[1] == "--fault":
        index = int(sys.argv[2])
        with FAULTS[index][1]():
            passed, failures = run_suite()
        print(json.dumps({"passed": passed, "failures": failures}))
        return 0

    print("baseline: the suite must be green before anything is broken")
    clean, failures = run_suite()
    if not clean:
        print(f"  the suite is already red: {failures[:5]}")
        return 1
    print("  green\n")

    # The failing test names are reported as a count and one example, not as "the test
    # that caught it". They come back sorted, so naming the first implies a causal link
    # that is not there -- a fault that breaks a shared invariant fails many tests at
    # once, and the alphabetically first one is rarely the relevant one.
    print(f"{'injected fault':46} {'caught':>7}  failing tests")
    caught = 0
    missed: list[str] = []
    for index, (name, _make) in enumerate(FAULTS):
        done = subprocess.run([sys.executable, __file__, "--fault", str(index)],
                              capture_output=True, text=True, cwd=str(ROOT.parent))
        try:
            answer = json.loads(done.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            print(f"{name:46} {'ERROR':>7}  {done.stderr.strip()[-120:]}")
            missed.append(name)
            continue
        passed, failures = answer["passed"], answer["failures"]
        if passed:
            missed.append(name)
            print(f"{name:46} {'NO':>7}")
        else:
            caught += 1
            print(f"{name:46} {'yes':>7}  {len(failures):>3}, e.g. {failures[0]}")

    print(f"\n{caught}/{len(FAULTS)} injected faults are caught by the test suite")
    if missed:
        print("not caught, and therefore a known gap:")
        for name in missed:
            print(f"  - {name}")
    return 0 if caught == len(FAULTS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
