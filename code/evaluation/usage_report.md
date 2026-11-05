# Token usage and cost

Generated 2026-10-25 08:25 UTC.

Run: all 518 requests in `dataset/deletion_requests.csv`, producing `output.csv`.
Cache: cleared before this run (cold).

## Totals

| | |
| --- | --- |
| requests processed | 518 |
| model calls | 40 |
| calls served from cache | 10 |
| input tokens | 441108 |
| output tokens | 15502 |
| total tokens | 456610 |
| average tokens per request | 881.5 |
| average model calls per request | 0.077 |
| estimated total cost | $0.0755 |
| estimated cost per request | $0.000146 |
| failed calls | 0 |
| wall clock | 171.2s |

## Per model

| provider | model | calls | input tokens | output tokens | cost |
| --- | --- | --- | --- | --- | --- |
| openai | `gpt-4o-mini` | 40 | 441108 | 15502 | $0.0755 |

Prices are the providers' published list prices per million tokens, recorded in
`code/audit/llm.py` so this total says where it comes from instead of being an
unsourced number.

## Why it is this small

Most of this agent does not use a model at all. Identity resolution, evidence
parsing, policy lookup, the gap computation, step ordering, numbering and
serialisation are deterministic code. Models are used in exactly two places:

1. **Intent classification** -- deciding whether a message authorises deletion.
   A keyword filter was measured first and reaches recall 0.400, because five of
   the ten non-deletion requests contain a deletion verb inside a negation.
2. **Screenshots** -- eleven of the ninety-four evidence files are application
   screens with no extractable text.

Three things keep the count down:

- **The corpus is fixed.** The same 94 evidence files answer all 518 cases, so
  each image is read once, not once per case. Eleven calls, not 5698.
- **Batching.** The 518 requests collapse to 375 distinct texts; classified 25
  per call that is about fifteen calls instead of 375 round trips, and one copy
  of the instructions is shared across each batch.
- **Caching on content.** Keys are the exact prompt and the file's own hash,
  never a case id, so two cases with the same wording share an answer and no
  case can be given a special one. Re-runs cost nothing.

The four PDFs were checked before being paid for: they are generated documents
with real fonts rather than scans, so their text is extracted directly and none
of them needs a vision call.

## Reproducing these numbers

```
python code/evaluation/make_reports.py --cold
```

`--cold` empties the cache first, so the figures above are what a clean run
costs. Without it the same run completes in under a second for nothing, which
is the steady state but not an honest headline.
