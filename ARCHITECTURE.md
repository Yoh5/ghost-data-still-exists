# Architecture

## The one idea

This looks like a search problem. It is a comparison.

For every record that belongs to the person, the agent works out two things:

- the state the **rules** require once the deletion is done, and
- the state the **evidence** shows at the case's audit time.

The difference between the two is the answer.

`COMPLETE` is not a separate branch of the code. It is simply the case where there is no
difference. That is not a style choice: in 21 of the 22 incomplete sample cases, the
verification block also covers records that needed no fix at all. So an incomplete case
and a complete one have the same shape. Two code paths would have had to agree with each
other forever, and one day they would not.

---

## The flow

```
  a deletion request
          |
          v
  +---------------+   Does this message ask for deletion?        no
  |    intent     | ------------------------------------------------>  NOT_APPLICABLE
  +---------------+                                                     with an empty plan
          | yes
          v
  +---------------+   The email may be current OR old. Build every
  |   identity    |   identifier this person has ever had.
  +---------------+   100 of 518 requests arrive on an old address.
          |
          v
  +---------------+   Read the 94 evidence files ONCE into one shape.
  |   evidence    |   Logs, SQL snapshots, JSON, PDFs, screenshots.
  +---------------+   This step reports facts. It never decides.
          |
          v
  +---------------+   Which records belong to this person?
  |   inventory   |   Evidence that names them, plus the records touched
  +---------------+   by the same block of deletion work.
          |
          v
  +---------------+   required state  <- deletion_rules.csv
  |    policy     |   observed state  <- the evidence, at audit_at
  +---------------+   The two halves never see each other.
          |
          v
  +---------------+   required vs observed
  |    engine     |     no gap   -> COMPLETE, verification only
  +---------------+     some gap -> INCOMPLETE: findings, fixes, checks
          |
          v
  +---------------+   Sort the steps the way the spec fixes.
  |     steps     |   Number them 1..n. Write output.csv.
  +---------------+   Then read the file back and check it.
          |
          v
      output.csv
```

---

## Where a model is used

Only in two places, and both are cached:

1. **intent** — deciding whether a message asks for deletion.
2. **vision** — reading the eleven screenshots.

Everything else is ordinary code: identity, parsing, policy, the comparison, the ordering,
the output. A full run over all 518 cases costs about **$0.07** and makes **0.07 model
calls per case**.

The reason is simple. The evidence corpus never changes, so it is read once and the 518
cases become lookups into it. Eleven images are read eleven times in total, not 518 times
each.

---

## What each file does

### The agent — `code/audit/`

| File | What it does |
|---|---|
| `dataset.py` | Loads the nine CSV files. It is the only place that touches `dataset/`, so the "participant data only" rule lives in one spot. It also checks the data looks the way we expect and stops if it does not. |
| `identity.py` | Finds the person behind an email address, including addresses they used in the past. Matching is exact: `jonas.berg@` must never match `jonas.berglund@`. If one identifier points to two people, it raises an error instead of choosing. |
| `evidence.py` | Reads every evidence file into one simple shape called an `Observation`. It handles ten log formats, SQL snapshots, JSON bundles, PDFs and a shift handover. **It only reports what a file says.** It never decides whether something is a problem. |
| `vision.py` | Reads the eleven screenshots with a vision model, once each, and caches the result. Anything it returns that is not a known kind of record is thrown away, because a screenshot is the one source that can invent an id. |
| `inventory.py` | Decides which records belong to the person. Two routes: evidence that names them, and the records touched by the same block of deletion work within an hour. Records that evidence gives to someone else are removed. |
| `policy.py` | Two separate questions. `required_state` reads the rules and never looks at evidence. `observed_state` reads evidence and never looks at the rules. Keeping them apart means neither can be tuned to agree with the other. |
| `engine.py` | Compares required with observed and writes the plan. This is where "when in doubt, do not say it is fine" lives: a record we cannot check blocks the COMPLETE verdict. |
| `steps.py` | The list of fifteen allowed operations and the order the spec fixes. Sorting and numbering are pure code, so they cannot be wrong in a surprising way. |
| `untrusted.py` | The request text is written by the public and goes into a prompt. This file wraps it safely and flags anything that looks like an attack. Key rule: an injected message can make the agent audit **more**, never less. |
| `intent.py` | Decides whether a message asks for deletion. It asks about 25 messages per call, then asks again, one at a time, about every message it wants to refuse. |
| `llm.py` | One small HTTP client for three providers. API keys come from the environment only. It counts every call and token, which is where the cost report comes from. |
| `scoring.py` | Measures the agent against the 32 published answers: status, steps, fields, order. It was written before there was anything to score. |
| `health.py` | The signals you would watch if this ran every night. The main one is surprising: a **rise** in COMPLETE verdicts is the warning sign, because a broken audit reports better results, not worse. |
| `main.py` | The entry point. Runs everything, writes `output.csv`, then reads that file back from disk and checks it against the submission contract. |

### Checking the work — `code/evaluation/`

| File | What it does |
|---|---|
| `score_samples.py` | Tests the scorer itself. Giving it the published answers must score 1.000. Shuffling the steps must break the order score and nothing else. A scorer that cannot fail is not a scorer. |
| `mutation_check.py` | Breaks the code 22 different ways, one at a time, and checks the tests notice. Each fault is a mistake someone could really make. |
| `own_cases.py` | Five test cases of our own, aimed at what the public answers cannot cover: a non-deletion request, a decoy address, the audit cut-off, an old email, and a prompt injection. |
| `sweep_attribution.py` | Replays every way of deciding which records belong to a person, including the ones we rejected, with their numbers. |
| `score_intent.py` | Compares the model against a simple keyword filter, and against an independent cross-check in the data. |
| `make_reports.py` | Generates the two required reports from a real run, so they cannot drift away from the code. |
| `check_pipeline.py` | A diagnostic: how many cases resolve, how much evidence is read, how much of the answer we can even see. |

### Tests — `code/tests/`

157 tests, standard library only.

| File | What it covers |
|---|---|
| `test_steps_and_scoring.py` | The step vocabulary, the ordering rule, and the scorer. |
| `test_identity_and_untrusted.py` | Matching addresses, and handling text written by an attacker. |
| `test_evidence_and_policy.py` | Every evidence reader, and the split between rules and observation. |
| `test_engine_and_output.py` | The verdict logic case by case, and the submission file read back from disk. |
| `test_llm_and_health.py` | The model client, the cache, the cost ledger, and the health signals. |
| `test_adversarial.py` | Inputs chosen to make us wrong: lookalike addresses, a huge message, a model reply that does not line up, and a snapshot that tries to write a file. |

---

## How to run it

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=...        # optional
python code/main.py
```

Without a key it still writes a valid `output.csv`; it just cannot find the ten
non-deletion requests, and it says so.

## How to check it

```bash
python -m unittest discover -s code/tests -t code   # 157 tests
python code/evaluation/mutation_check.py            # 23 faults, all caught
python code/evaluation/own_cases.py                 # our 5 cases
python code/main.py --samples                       # score on the 32 answers
```

---

## Three sentences to remember

1. **Evidence is read once; cases are lookups into it.** That is why the run costs seven
   cents.
2. **Reading and judging are separate.** A parser bug cannot quietly become a wrong
   verdict.
3. **The order of the steps is code, not a model.** Taking each published answer,
   shuffling it, and re-deriving the order reproduces it exactly, 32 times out of 32.
