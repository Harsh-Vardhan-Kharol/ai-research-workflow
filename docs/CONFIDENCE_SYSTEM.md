# Confidence System

## Meaning

> The confidence score represents the system's estimated confidence in the
> quality and evidential support of an extraction. It is not a calibrated
> probability that the extracted statement is objectively true.

The score is a deterministic estimate based on validated extraction data and
independently persisted evidence. It is not an LLM self-rating, a guarantee of
correctness, or a scientific truth score. Evidence matching establishes source
traceability only; fuzzy text similarity does not establish factual correctness.

## Formula

For every persisted extraction item:

```text
C = 0.30*S + 0.40*E + 0.20*R + 0.10*K
```

All signals are in `[0, 1]`; weights sum to `1.00`. The score is rounded to six
decimal places after calculation. Invalid inputs are rejected rather than
clamped. Invalid extractions are not materialized by Phase 4 and therefore do
not receive a score.

| Signal | Weight | Deterministic calculation |
|---|---:|---|
| `schema_validity` (S) | 0.30 | `1.0` for a persisted item from a strictly Pydantic-validated successful group. Failed groups/items are not scored. Phase 4 does not persist a repair-attempt indicator, so no `0.5` retry value can be derived; valid persisted items receive `1.0`. |
| `evidence_strength` (E) | 0.40 | Use only persisted Phase 5 evidence. For `MATCHED`, use its independently computed `evidence_score`; for `WEAK`, `UNAVAILABLE`, or `FAILED`, use `0.0`. A weak candidate remains visible as evidence but is below the configured matching threshold. No evidence row is treated as unavailable and contributes `0.0`. |
| `source_relevance` (R) | 0.20 | `1.0` when the matched evidence section corresponds to the expected extraction-group section in `AI_ARCHITECTURE.md` (metadata also receives `1.0` for page 1); `0.5` when the group used whole-document fallback and a matched page exists; `0.0` when there is no matched page or the detected-section path cannot trace the passage to an expected section. The AI-proposed section is never used. |
| `completeness` (K) | 0.10 | `1.0` for a non-empty validated item that is not a recognized placeholder (`N/A`, `not applicable`, `not reported`, `not specified`, `not available`, `unknown`, `null`, `none`, or `insufficient information`); `0.0` for those placeholders. Null values are omitted before materialization. List fields are split into one item per extraction row, so a missing list item is not scored or penalized. |

No additional consistency model is supported by the current architecture; no
cross-field semantic model, repeated LLM sampling, or cross-paper comparison
is performed. Completeness is limited to explicit value presence, not whether a
paper reported a particular topic.

## Levels and routing

Level is computed from score:

| Score | Level |
|---|---|
| `>= 0.75` | `HIGH` |
| `>= 0.45` and `< 0.75` | `MEDIUM` |
| `< 0.45` | `LOW` |

Review routing is separate from the score and level. `review_required` is true
when any of these conditions applies:

- Evidence is `UNAVAILABLE`: `evidence_unavailable`.
- Evidence is `FAILED`: `evidence_mapping_failed`.
- Evidence is `WEAK`: `evidence_weak`.
- The level is `LOW`: `low_confidence_score`.

Reasons are emitted in that order when multiple conditions apply. A missing
evidence record is treated as unavailable, scores `E = 0`, has no matched page
for `R` (`R = 0`), and requires review. Under the current weights, its maximum
numeric score is therefore `0.40` (LOW), even with all other signals at `1.0`.
The routing reason remains explicit and independent of score calculation. It
cannot be safely auto-accepted: `review_required` routes it to `PENDING_REVIEW`
regardless of level. A `MATCHED` record may be automatically accepted when its
level is not LOW. MEDIUM remains accepted with review suggested by its level;
weak evidence and all unavailable/failed evidence require review.

This resolves the former open zero-evidence question: keep the documented
weighted formula and thresholds, and force review through the independent
routing property rather than distorting the score. `FAILED` evidence is not
proof that a claim is false; it means mapping could not be evaluated.

## Result and persistence

The extraction API returns the following fields after scoring:

```json
{
  "confidence_score": 0.91,
  "confidence_level": "HIGH",
  "confidence_signals": {
    "schema_validity": 1.0,
    "evidence_strength": 0.9,
    "source_relevance": 1.0,
    "completeness": 1.0
  },
  "review_required": false,
  "review_reasons": [],
  "status": "ACCEPTED"
}
```

The values above are illustrative. Signal and reason JSON is stored on the
extraction row because this is one explainable result per claim; it avoids a
redundant confidence table. `status` is `PENDING_REVIEW` when review is
required and `ACCEPTED` otherwise. Human review actions remain a later phase.

Phase 10 limitation and future-work items use this same formula, signals,
levels, and routing. Their section relevance set includes the headings listed
in `AI_ARCHITECTURE.md`. The weights and meanings of S, E, R, and K do not
change. No confidence is created for an empty list; every non-null claim is
scored after its evidence record is persisted.

## Input validation and failures

Signals and evidence scores must be finite numbers in `[0, 1]`; booleans are
not accepted as numbers. Unknown evidence states, malformed matched passage
metadata, or inconsistent unavailable/failed records stop confidence
processing safely. Missing evidence is the sole absent-record case and routes
to review. Calculated values are never clamped. Persistence of all item
results and the paper transition to `READY` occurs atomically. A calculation
or database failure leaves the paper out of `READY` with a safe failure reason.

## Limitations

- A fluent, well-matched, but factually wrong statement can receive a high
  score.
- Fuzzy evidence matching checks traceability, not semantic support or truth;
  a superficially similar passage can inflate the matched evidence score.
- Multi-passage claims can score lower even when correct.
- No cross-field, cross-paper, or cross-run consistency checking is included.
- The score is not calibrated against human judgments and should not be read
  as a probability.

## Deviation Log

- 2026-09-28: Resolved zero-evidence handling. Preserve the documented score
  formula and thresholds, but route unavailable, failed, and weak evidence to
  review independently of level. This prevents a high structural score from
  causing safe acceptance with no strong traceability.
- 2026-09-28: Phase 5's actual evidence contract supersedes the earlier proposal
  to recompute similarity in confidence: confidence consumes only persisted
  matched evidence and never treats the AI-proposed passage as verified.
- 2026-09-28: The Phase 4 checkpoint does not retain repair attempts or
  partially valid items; schema validity is `1.0` for persisted claims. The
  former hypothetical `0.5` retry value cannot be computed from stored data.
