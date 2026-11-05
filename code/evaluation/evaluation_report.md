# Evaluation report

Generated 2026-10-25 08:25 UTC from a full run.

## What is measured, and against what

`dataset/sample_output.csv` gives correct answers for the 32 public sample
cases. They are separate from the 518 cases to be predicted, and they are the
only labelled data in the challenge. Every number in this section is measured
against them. Numbers measured any other way say so explicitly.

The scorer itself is self-tested in `code/evaluation/score_samples.py`: feeding
the published answers back in as predictions must return 1.000 on every metric,
and shuffling the steps must collapse sequence accuracy while leaving step F1
untouched. A scorer that cannot fail is not a scorer.

## Case-level status accuracy

| strategy | status accuracy |
| --- | --- |
| always INCOMPLETE (majority class) | 0.688 |
| always COMPLETE | 0.312 |
| trust the workflow's `reported_status` | 0.531 |
| **this agent** | **0.969** |

The internal workflow's own `reported_status` scores **0.531** -- worse than
answering INCOMPLETE to every case without looking at anything. That is the
$2.4m failure in the problem statement, measurable in the supplied data, and it
is why no activity result or workflow status is ever treated as proof here.

### Confusion matrix

```
gold \ pred     COMPLETE    INCOMPLETE  
COMPLETE        10          0           
INCOMPLETE      1           21          
```

## Step-level, field-level and sequence accuracy

| metric | value |
| --- | --- |
| step precision | 0.976 |
| step recall | 0.829 |
| step F1 | 0.896 |
| field accuracy | 0.718 |
| sequence accuracy | 0.312 |
| evidence citation accuracy | 0.827 |

Step identity is `(phase, operation, system_id, resource_id, state)`, compared
as multisets so order is ignored. Sequence accuracy is a separate, stricter
measure: the step array must match position for position. `evidence_id` is
scored on its own, because citing the wrong file is a different failure from
finding the wrong record and averaging the two would hide both.

### Where the remaining error is

| operation | missing | spurious |
| --- | --- | --- |
| `VERIFY_RECORD_ABSENT` | 20 | 1 |
| `VERIFY_RECORD_ANONYMIZED` | 4 | 3 |
| `DELETE_RECORD` | 3 | 0 |
| `REPORT_REMAINING_RECORD` | 3 | 0 |
| `VERIFY_RECORD_PRESENT` | 3 | 0 |

Precision is 0.976: the agent rarely reports a record that should not be
there. The error is almost entirely recall, and a measured part of it cannot be
recovered at all:

**17 of the 193 steps in the published answers name a resource that appears in no
participant-visible evidence whatsoever** -- not in the CSVs, not in the logs,
not in the SQL snapshots, not in the PDFs, not in the screenshots. They are
mostly deleted accounts: account_001, account_002, account_004, account_006, account_007, account_008....

We tried to recover them. In the window between a case's `requested_at` and its
`audit_at`, the deletion worker's `DELETE_RECORD` rows on `account_service` do
contain the right account in 21 of 22 cases -- but alongside 8 to 43 others, and
nothing in the data distinguishes them. Picking one would be guessing, and
adding all of them would cost roughly thirty false exposures per case. So this
exposures per case. So this
is reported as a ceiling rather than hidden. 17 of the 111 resources the
answers name appear nowhere, and they carry 17 of the 193 steps, so **step
recall cannot exceed 0.912 on this corpus**. The agent reaches
0.829, which is 91% of what the data allows.

That ceiling was quoted as 0.85 in an earlier version of this report, which was
the figure counted per RESOURCE (94 of 111 reachable). The metric reported here
is step recall, and counted per step the ceiling is 0.912. The lower number
flattered the result and has been corrected.

## Tests, and whether they would notice

`python -m unittest discover -s code/tests -t code` runs 157 tests
with no dependency beyond the standard library. They cover the step vocabulary
and the ordering the spec fixes, identifier matching, every evidence reader,
the split between what a rule requires and what evidence shows, the verdict
logic case by case, the handling of untrusted text, and the submission contract
read back off disk.

A green suite proves the tests ran, not that they would notice a regression. So
`code/evaluation/mutation_check.py` breaks the code twenty-three ways, one fault at a
time, and checks the suite goes red. Each fault is a mistake someone could
actually make here, and several were made and fixed during this build: step
order ignoring phase, an unestablished state counting as absent, a log line
allowed to prove redaction, the verdict taken from `reported_status`, the
`audit_at` cutoff dropped, future work citing evidence, an injected refusal
accepted, an unchecked backup passing as blocked, a screenshot inventing a
resource, the answer depending on the case id.

**23 of 23 are caught.** That number is the second one this harness produced,
and the first one was wrong.

It first reported 12 of 12. Checking one result by hand found two problems, both
in the harness rather than in the code. `engine.py` does `from .policy import
observed_state`, so it holds its own reference and patching `policy.observed_state`
left the engine untouched: one fault was simply inert. And the faults ran in a
single process, so effects leaked from one run into the next and inflated the
count -- the inert fault was being credited to failures caused by the previous
one. Each fault now runs in its own process and is patched everywhere the name is
bound. The honest number was then 13 of 15, which exposed two genuine gaps in the
tests: nothing covered the one-resource-per-system rule, and nothing covered the
rejection of placeholder identifiers. Both are now tested, and the fifteen are
caught for real.

A mutation harness that lies is worse than none, because what it certifies is the
test suite.

## Our own evaluation cases

The public set is narrow in three specific ways: it contains no
`NOT_APPLICABLE` case at all, it never tests whether a decoy identifier is kept
out, and it cannot show whether the `audit_at` cutoff is enforced, because every
sample runs at exactly one cutoff. These four cases, in
`code/evaluation/own_cases.py`, assert properties rather than remembered
answers, so they keep working if the data changes.

**non-deletion request yields NOT_APPLICABLE and an empty plan** -- PASS  
Protects: the third verdict class, which the public answers never exercise  
Checks: 6/6 passing

**a decoy identifier is never matched** -- PASS  
Protects: exact identifier matching; the failure mode that invents exposures  
Checks: 8/8 passing

**the audit_at cutoff is enforced** -- PASS  
Protects: point-in-time correctness; later evidence must not change an answer  
Checks: 7/7 passing

**a historical identifier resolves to the same subject** -- PASS  
Protects: the failure that created the ghost in the first place  
Checks: 7/7 passing

**an injected message cannot suppress an audit** -- PASS  
Protects: the one verdict worth attacking, and the only one that stops us looking  
Checks: 10/10 passing

Two of them failed when first written, and both times the test was wrong rather
than the code: the decoy address is not a registered subject at all, and moving
a cutoff backwards legitimately changes which snapshot is the most recent one
available. Both assertions were corrected to state the property that actually
matters.

## Failures found, and what they changed

Every row is a measurement taken before and after a single change.

| # | what was wrong | status | step F1 |
| --- | --- | --- | --- |
| 1 | first end-to-end run | 0.719 | 0.424 |
| 2 | activity-burst attribution pulled in other people's records: 123 spurious verification steps across 32 cases | 0.688 | 0.580 |
| 3 | burst attribution disabled entirely after measuring it against evidence-only linkage | 0.688 | 0.627 |
| 4 | log lines were read independently, so the identifier on the `_started` line never met the resource id on the `_completed` line -- 27 resources belonged to nobody | **0.781** | 0.671 |
| 5 | `account_status` was read as the record's own state, so a tombstone saying DELETED hid the name, email, phone and hash it still carried | 0.938 | 0.684 |
| 6 | PDFs turned out to carry extractable text; one of them is the evidence a published answer cites | **0.969** | 0.697 |
| 7 | read-back traces report a record's fields explicitly, nulls included, and were being treated as mere mentions | 0.969 | 0.758 |
| 8 | a service export's `profile_lookups` section was read as profiles; a `status_code` of 404 is the service saying there is no record | 0.969 | 0.766 |
| 9 | attribution by contiguous activity ids within an hour, one resource per system | 0.969 | 0.812 |
| 10 | proof of absence was refused for resources linked through the subject's own deletion run | 0.969 | 0.812 |
| 11 | the JSON bundles' and service exports' own section names were unmapped, so a support attachment could not be told from a conversation | 0.969 | 0.812 |
| 12 | the treatment required by policy was read from the data category alone, never from the operation the deletion run attempted | 0.969 | 0.846 |
| 13 | the state came from the most recent observation rather than the most recent one that said anything, so a later silent log buried an earlier `restore_allowed` | 0.969 | 0.856 |
| 14 | a backup whose restore status nobody established was treated as compliant | 0.969 | 0.866 |
| 15 | a PII scan line naming the identifier it matched was read as an event with no content | 0.969 | 0.876 |
| 16 | a record nobody can claim, sitting where two deletion runs meet, was attributed to both neighbours | 0.969 | 0.883 |
| 17 | a retained record identified only by later evidence got no check at all, when a check is future work and needs no citation | 0.969 | 0.893 |
| 18 | two log formats write a JSON object per line, and the tokeniser only understood `key=value`, so every field saying whose record it is was dropped in silence | **0.969** | **0.896** |

Two routes to the remaining recall were tried and measured away. Letting ANY
activity row on a grounded resource locate the deletion run reaches no further:
step recall is identical and F1 falls from 0.866 to 0.859. Enumerating every
contiguous run inside a case's own request window and keeping those with no
conflicting owner reaches 0.162 recall with 137 spurious resources. Both are
kept in `sweep_attribution.py` so they are not retried.

### One distinction worth stating plainly

`reported_result` and `reported_status` are claims about what happened, and this
solution ignores both: trusting them scores 0.531. But the *operation type* on an
activity row is not a claim about state. It is the organisation's own reading of
its deletion policy for that record, written down before the attempt and often
followed by `FAILED`.

That distinction is worth 0.034 of step F1 on its own, and it is the only thing
in the data that separates two records the rules cannot: `support_002` and
`support_864` are both support records with indistinguishable ids, and the
deletion run says the first was to be deleted under rule_06 and the second
redacted under rule_05 -- exactly as the published answers treat them. The run is
never asked whether it succeeded; `reported_result` is read nowhere in this
solution. `rules-first` is still available in `sweep_attribution.py` so the
comparison can be re-run.

Three things were tried, measured and reverted, and the numbers are recorded
next to the code so the attempts are not repeated:

- **Request-bounded attribution window.** Recall 0.396, precision 0.071, against
  0.775 / 0.287 for the burst window it was meant to replace.
- **Decoupling linkage time from state time.** Step recall rose 0.513 to 0.523
  and it is the only route to 7 named resources, but two correct COMPLETE
  verdicts were lost and status fell 0.781 to 0.750 for no change in step F1.
- **A resource-numbering convention** (`user_01` -> `account_001`), which holds
  for the first few cases and for 8 of 111 overall. Nothing depends on it.

## What the agent does when it cannot tell

`UNKNOWN` is a state, and it never decays into a compliant one.

- A resource tied to the subject by evidence whose state cannot be established
  blocks the `COMPLETE` verdict, because an unaudited copy reported as deleted
  is the exact failure in the problem statement.
- A *retained* record whose state cannot be confirmed is a gap in our proof of
  retention, not evidence that prohibited data survives, so it is recorded and
  does not overturn the verdict. The two failures are not the same size.
- Absence is never inferred from silence. It is established only by evidence
  that enumerates a system and does not contain the subject.
- An identity that resolves to more than one person raises instead of picking.
- A `NOT_APPLICABLE` verdict suppresses an entire audit, so each one is
  confirmed by a second, individual model call before it is accepted.

## Reproducibility

Everything except two steps is deterministic code, and both model-backed steps
run at temperature 0 with their answers cached on content -- the exact prompt
for intent, the file's own hash for a screenshot. Given the same cache, the
same input produces a byte-identical `output.csv`; that was checked across the
working tree, a staged copy in a fresh virtual environment, and `code.zip`
extracted into an empty directory with only `dataset/` beside it.

**Cold runs are not guaranteed identical, and this report would rather say so
than claim otherwise.** The screenshot pass is the one step that can vary: at
temperature 0 it returned 19 records on one run and 20 on another. Two cold runs
of the same code were observed to differ by one case verdict and two steps out
of roughly 2370 -- about 0.2% of the plan and 0.2% of the cases. The
deterministic core never moved.

That is the honest shape of it: a reproducible engine, one step that is not, and
a cache that makes every repeat of a given run exact. Running with
`--no-vision` removes the variation entirely, at the cost of the screenshots.

The solution also runs with no model provider configured at all. It writes a
valid `output.csv`, cannot identify the ten non-deletion requests, and says so
on stdout instead of letting a default look like a judgement.

## Untrusted input

`request_text` is attacker-controlled and goes into a model prompt. The payoff
for an injection is specific: `NOT_APPLICABLE` is the only verdict that stops
the agent looking, so a message that talks the classifier into it returns an
empty plan and leaves the data in place.

The defence that carries the weight is structural rather than statistical: an
injected message may cause *more* auditing, never less. A refusal to audit is
rejected when the message carries injection markers, whatever the model said.
The model does not have to win. On top of that the message is fenced in a
delimiter it cannot contain, its own fences and batch numbering are defanged,
invisible characters are stripped, and in the batch prompt each message is
numbered outside its own fence so it cannot forge a neighbour's header.

None of the 518 supplied requests trips the detector. Three crafted attacks are
contained, and a genuine access request is still correctly NOT_APPLICABLE, so
the guard is not simply answering yes to everything.

### Evidence SQL is executed, so it is confined

SQL snapshots are run with `sqlite3` rather than pattern matched, because a regex
over INSERT statements mis-splits any value containing a comma or a quote and
these files carry names and message excerpts. The cost is that the agent executes
a file somebody else wrote.

That is a real surface, not a theoretical one. A snapshot containing
`ATTACH DATABASE '/elsewhere.db' AS out; CREATE TABLE out.x (c);` writes a file
outside the in-memory database. It was tried, and it worked.

The connection now runs behind a deny-by-default authorizer. The allowed list was
not guessed: an authorizer was first run in trace mode over a real snapshot to see
what it actually asks for -- create table and index, insert, read, transaction,
reindex, and one pragma. ATTACH, DETACH, `writable_schema` and
`temp_store_directory` are refused. A block list would only stop the attacks
somebody already thought of, and these files are executed before anyone has read
them.

Six tests cover it, including one that shows the attack SUCCEEDING without the
guard before showing it blocked -- otherwise the test would prove nothing.

## Monitoring

An audit agent fails quietly: it does not crash when it starts missing copies,
it returns COMPLETE. `python code/main.py --health` emits the signals that
would catch that, with thresholds and a non-zero exit.

The leading signal is counter-intuitive: **a rise in COMPLETE verdicts is the
alarm**, because an agent that stops finding records reports better results. A
dashboard watching an error rate would stay silent through exactly this
failure. Alongside it: cases blocked by an unestablished state, evidence files
that could not be read — kept strictly apart from files read and legitimately
empty, because those need different actions — unresolved identities, model-call
failures, injection attempts, and cost per run.

## Output

- 518 rows, 189 COMPLETE, 319 INCOMPLETE, 10 NOT_APPLICABLE
- 2602 steps
- 115 cases carry at least one recorded uncertainty
