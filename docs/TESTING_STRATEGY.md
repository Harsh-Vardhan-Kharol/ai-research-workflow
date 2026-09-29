# Testing and Evaluation Strategy

Software tests and empirical evaluation answer different questions. Tests
check whether the implementation follows its contract on controlled inputs.
Evaluation compares model predictions with independent annotations on a
defined dataset. Passing tests is not an extraction accuracy result.

## Test layers

| Layer | Scope | Current approach |
|---|---|---|
| Unit tests | Schemas, section detection, evidence matching, confidence formula/routing, normalization, insight grounding | `tests/test_*.py`, deterministic inputs |
| Integration tests | PDF processing, persistence, evidence/confidence writes, atomic review, retry/failure handling | Temporary SQLite databases and mocked providers |
| API tests | Upload, processing, extraction, evidence, review, comparison, insight request/response and error envelopes | FastAPI `TestClient` |
| End-to-end tests | Upload PDF through processing, comparison and insights | Local PDF fixtures, mock provider; no paid service |
| Evaluation benchmarks | Extraction and evidence predictions against independent reference annotations; deterministic analytics against controlled expected results | `data/evaluation/` and `scripts/evaluate.py` |
| Failure injection | Corrupt/empty/duplicate/invalid/oversized PDFs, provider errors/timeouts/malformed output, invalid evidence, DB writes, invalid transitions and references | Explicit regression tests |
| Manual UI smoke tests | Streamlit navigation, rendering, evidence visibility, review controls and comparison display | Follow `docs/DEMO_GUIDE.md`; browser rendering is not automated |

Phase 8 covers frontend response/error parsing and review payloads. Phase 9
covers comparison normalization, selection, frequency traceability, pairwise
differences, patterns, and missing information. Phase 10 covers
limitations/future-work claims and deterministic gap rules. Phase 11 covers
bounded insight input, escaped untrusted data, mock-provider responses,
grounding, duplicate/size controls, invalid references, and API errors.
Streamlit browser rendering is not asserted.

## Phase 12 dataset and matching

`data/evaluation/papers.json` contains ten short, locally authored synthetic
papers with page boundaries and varied headings, methods, datasets, metrics,
limitations, future work, missing fields, and a prompt-injection string.
`data/evaluation/annotations.json` contains human-authored expected values and
verbatim page evidence, authored independently from model output. These are
compact evaluation fixtures, not external publications.

Prediction files passed with `--predictions` use a `papers` object keyed by
fixture ID, then extraction field, then arrays of `{"value": ..., "evidence":
{"page": 1, "quote": ...}}`. Expected values use the extraction schema's
field names and one record per list claim; scalar claims use the same one-item
list representation for scoring. A missing prediction is missing output. An
empty reference list means the field was annotated and no claim was expected;
any prediction for it is counted as an incorrect extra. A missing annotation
field is NOT_APPLICABLE, and a null reference is UNAVAILABLE; both are excluded
from extraction denominators.

Item matching is one-to-one with global priority passes: exact string equality
for all expected items first, then NFKC/casefold/punctuation/whitespace
equality, then partial match for Jaccard token overlap of at least 0.5. Only exact and normalized matches count as true
positives for precision, recall and F1. Partial, missing, and extra incorrect
items remain separately visible. Field coverage is the fraction of annotated,
available paper-field pairs with a prediction key, including an empty list.
Evidence is correct only when the normalized
quoted passage occurs on the claimed one-based page. A quote on another page is
incorrect; weak token overlap on the claimed page is WEAK; no quote/page is
UNAVAILABLE. Evidence precision uses correct/predicted evidence items, and
recall uses correct/annotated evidence items. Lexical matching does not prove
that a passage entails a claim.

Without a separately produced model prediction file, extraction and evidence
performance are reported as **Not measured**. The null mock provider is not
scored as an extraction model. Confidence scores are deterministic routing
scores, not calibrated probabilities. Comparison and gap-rule correctness are
tested against hand-authored synthetic database fixtures, not generalized to
research literature.

## Reproduce

From the repository root:

```bash
.venv/bin/python scripts/evaluate.py
PYTHONPATH=. .venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app frontend tests scripts
git diff --check
```

The runner writes `data/evaluation/evaluation_results.json` and prints the
same structured result. Optional independently generated predictions can be
scored with `.venv/bin/python scripts/evaluate.py --predictions
path/to/predictions.json --output path/to/results.json`. Do not use application
output as its own reference or silently convert absent predictions into
successful matches.

## Existing subsystem regression coverage

- PDF -> parser -> section detection -> database: page text and bounded section
  rows persist.
- PDF -> parser -> extraction with a fixed provider -> database: validated
  groups persist; invalid groups do not become successful payloads.
- Validated extraction -> stored page lookup -> evidence mapping -> database:
  proposed and matched provenance remain separate.
- Evidence -> confidence -> SQLite -> extraction API: deterministic score,
  signals and review routing persist.
- Pending extraction -> Accept/Edit/Reject -> SQLite -> GET: terminal state,
  one review record, immutable AI value, reviewed value/comment/timestamp, and
  unchanged paper status. Invalid input, duplicate review and rollback are
  covered.
- Failure paths cover PDF failures, provider retries and errors, evidence and
  database failures, invalid selections, and insight validation.
- Offline PDF upload -> processing -> READY -> comparison -> mock insights is
  exercised without a live provider.

## Acceptance criteria for a feature

A feature is complete only when it has tests at the applicable layers,
relevant failure paths are covered, and documentation accurately describes
the behavior. Do not describe an empirical model metric unless it was
calculated from predictions against these independent references.
