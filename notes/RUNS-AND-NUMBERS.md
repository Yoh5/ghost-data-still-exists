# The commands and the numbers

Simple English. Open this during the interview.

---

# Part 1 — The commands

First, go to the project folder:

```powershell
cd "C:\Users\hp\Projet Persos\AI\orchestrate\repo"
$env:OPENAI_API_KEY = "<your key>"
```

---

## Command 1 — The tests

```powershell
python -m unittest discover -s code\tests -t code
```

**What it is:** 157 tests. They use only the Python standard library.

**What it checks:** that each part does what it promises. The step rules. The way we match
email addresses. Every evidence reader. The split between rules and evidence. The verdict
logic. The output file, read back from disk.

**What you see:**
```
Ran 157 tests in 13s

OK
```

**What it means:** `OK` means all 157 pass. If one fails, it prints the name and the line.

**Takes:** 13 seconds.

---

## Command 2 — Our own test cases

```powershell
python code\evaluation\own_cases.py
```

**What it is:** five cases I wrote myself. The challenge asks for at least three.

**What it checks:** the holes in the published answers. Those 32 answers have no
NOT_APPLICABLE case. They never test a decoy address. They cannot show that the audit
cut-off works, because each one runs at a single cut-off.

**What you see:**
```
PASS  non-deletion request yields NOT_APPLICABLE and an empty plan
PASS  a decoy identifier is never matched
PASS  the audit_at cutoff is enforced
PASS  a historical identifier resolves to the same subject
PASS  an injected message cannot suppress an audit
5/5 own evaluation cases pass
```

**What it means:** each line says what it protects. All five hold.

**Takes:** 10 seconds.

---

## Command 3 — The score

```powershell
python code\main.py --samples
```

**What it is:** the agent runs on the 32 cases that have known answers, and compares.

**What you see:**
```
n=32  status 0.969  sequence 0.312  steps P0.976/R0.829/F1 0.896  fields 0.718  evidence 0.827
gold \ pred     COMPLETE    INCOMPLETE
COMPLETE        10          0
INCOMPLETE      1           21
```

**How to read the table:** rows are the true answer. Columns are my answer.
- 10 cases are COMPLETE and I said COMPLETE. Correct.
- 21 cases are INCOMPLETE and I said INCOMPLETE. Correct.
- 1 case is INCOMPLETE and I said COMPLETE. Wrong.
- 0 cases are COMPLETE where I said INCOMPLETE.

**The important part:** the top row reads **10 and 0**. I never say the data is gone when
it is not. That is the dangerous direction, and it is empty.

**Takes:** 10 seconds.

---

## Command 4 — The real run

```powershell
python code\main.py
```

**What it is:** the run that makes the file you submit.

**What you see:**
```
output.csv passes the contract: 518 rows, columns ['case_id', 'deletion_status', 'steps_json']
statuses: {'INCOMPLETE': 319, 'COMPLETE': 189, 'NOT_APPLICABLE': 10}
total steps: 2602
```

**What it means:** the agent wrote `output.csv`, then **read its own file back from disk**
and checked it. Row count, column order, case order, allowed statuses, valid JSON, step
numbers 1 to n, empty plan for every NOT_APPLICABLE.

**If you see `passes the contract`, the file is safe to submit.**

**Takes:** 1 second when the cache is warm. About 3 minutes the first time with a key,
because it reads the eleven screenshots.

---

## Command 5 — Breaking the code on purpose

```powershell
python code\evaluation\mutation_check.py
```

**What it is:** it breaks the code 23 different ways, one at a time, each in its own
process. Then it checks that the tests turn red.

**What you see:**
```
23/23 injected faults are caught by the test suite
```

**What it means:** a green test suite only proves the tests ran. This proves they would
notice if something broke.

**Takes:** about 10 minutes.

---

## If you have no API key

```powershell
python code\main.py --no-intent --no-vision
```

It still writes a valid `output.csv`. It cannot find the ten non-deletion requests, and it
says so on screen. Nothing fails silently.

---

# Part 2 — The numbers

## Say this first, about any number

> Everything I quote is measured against `dataset/sample_output.csv`. That file has the
> correct answers for 32 cases. It is the only ground truth in this challenge. The 518
> cases I submit have no published answers, so I never claim a score on them.

---

## The verdicts

| Number | What it means |
|---|---|
| **0.969** | Out of 32 cases with known answers, I am right **31 times**. |
| **0.688** | What you get by saying INCOMPLETE to every case, without looking. 22 of the 32 are INCOMPLETE. This is the bar to beat. |
| **0.531** | What you get by copying the company's own status. **Worse than guessing.** |
| **10 / 0** | All ten truly COMPLETE cases found, and zero false ones. |

> Their dashboards all said "Complete". I measured that status: it scores 0.531. Saying
> INCOMPLETE to everything, blind, scores 0.688. Their claim is worse than guessing.

---

## The plan of steps

A step is: phase, operation, system, resource, state.

| Number | What it means |
|---|---|
| **Precision 0.976** | Of 100 steps I propose, about 98 are correct. I rarely invent work. |
| **Recall 0.829** | Of 100 steps they expect, I find about 83. |
| **F1 0.896** | The two together. The single summary number. |
| **Sequence 0.312** | Cases where my list matches theirs **position by position**. Very strict. |
| **Fields 0.718** | Share of fields that match. |
| **Evidence 0.827** | Share of correct evidence citations. |

**If the judge says sequence is low:**

> It is low, and it is a recall effect, not an order effect. One missing step breaks the
> whole case. Where my set of steps equals theirs, the order is right 9 times out of 9.
> Across every case with steps in common, the order is right 28 times out of 28.

---

## The ceiling

| Number | What it means |
|---|---|
| **17 of 111** | Resources named in the answers that appear in **no evidence file at all**. |
| **17 of 193** | The steps those resources carry. |
| **0.912** | So recall cannot go higher than (193 − 17) / 193. |
| **91%** | 0.829 divided by 0.912. How much of the reachable answer I reach. |

> Seventeen resources appear nowhere in the data. I reach 0.829, about 91% of what the data
> allows. I quoted 0.85 for a while, counted per resource. The metric I report is per step,
> so that number flattered me. I corrected it.

---

## Three facts about the data

All three measured on the 32 published answers.

| Number | What it proves |
|---|---|
| **32/32** | I take each answer, **shuffle** its steps, and sort them again with my rule. Identical every time. **The order is code, not a model.** |
| **111/111** | Every case names exactly one resource per system. |
| **21/22** | Incomplete cases also verify records that needed no fix. So COMPLETE is not a separate code path. |

---

## Intent — measured on all 518

No sample case is NOT_APPLICABLE. So I built a reference by grouping the 518 texts.

| Number | What it means |
|---|---|
| **10** | Non-deletion requests among the 518. |
| **0.400** | Recall of a simple keyword filter. It misses **6 of the 10**. |
| **1.000 / 1.000** | Precision and recall of my classifier. |
| **0.833 → 1.000** | The gain from asking again about every refusal, one at a time. |
| **100 of 518** | Requests that arrive on an **old** email address. |

> Five of the ten contain a deletion verb inside a negation, like "I am not asking for
> deletion". A keyword filter gets those backwards.

---

## Tests, security and cost

| Number | What it means |
|---|---|
| **157 tests** | The whole suite. Standard library only. |
| **23 of 23** | Faults I inject on purpose, all caught by the tests. |
| **5 of 5** | My own evaluation cases. |
| **about $0.07** | A full run over all 518 cases, from a cold cache. |
| **0.07 calls per case** | 37 model calls divided by 518 cases. |
| **19 vs 20** | The screenshot pass gave 19 records on one run and 20 on another. The only variable step. |

**On security:**

> Evidence SQL files are executed, so that is a real surface. I wrote the attack and ran
> it: a snapshot with `ATTACH DATABASE` wrote a file outside the in-memory database. It
> worked. The connection now runs behind a deny-by-default authorizer. Six tests cover it,
> and one of them shows the attack succeeding without the guard first, because a test that
> only shows the blocked case proves nothing.

---

## If you forget a number

> I do not have that in my head, but I can show you where it is measured.

Every number here comes from one command. They are all written into
`evaluation_report.md` and `usage_report.md` inside the submission.

**Never invent a figure.** One wrong number, and the judge will doubt all the others.
