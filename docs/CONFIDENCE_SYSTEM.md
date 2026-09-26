# Confidence System

## Statement that must appear in the product UI and docs verbatim

> The confidence score represents the system's estimated confidence in the
> quality and evidential support of an extraction. It is not a calibrated
> probability that the extracted statement is objectively true.

## Why the originally proposed formula was revised

The original formula (`0.20S + 0.40E + 0.20R + 0.20K`, with `K` as an
undefined "consistency" signal) had two problems:
1. It over-weighted evidence strength (40%) as if evidence absence were
   equally as damning as evidence contradiction — but a correct claim can
   legitimately lack a clean quotable passage (e.g., a fact stated only
   implicitly across a paragraph).
2. "Consistency" as originally implied would require re-sampling the same
   extraction multiple times to check agreement — expensive (multiple extra
   LLM calls per field) and not clearly worth it for a 7–14 day MVP.

## Revised formula (authoritative)

```
C = 0.30*S + 0.40*E + 0.20*R + 0.10*K
```

All components normalized to [0, 1].

| Symbol | Signal | How it's computed (deterministic) |
|---|---|---|
| S | Schema/structural validity | 1.0 if the field passed Pydantic validation cleanly and is non-empty and non-placeholder (e.g. not literally "N/A" text); 0.5 if valid but required a repair retry; 0.0 if validation ultimately failed (item is discarded, not scored) |
| E | Evidence strength | `rapidfuzz` similarity ratio (0–1) between the AI's claimed `source_text` and the actual text of the cited page/section; 0.0 if no evidence was returned at all |
| R | Source relevance | 1.0 if the evidence's cited section matches the expected section for that extraction group (see `AI_ARCHITECTURE.md` table); 0.5 if evidence came from the whole-document fallback path; 0.0 if no page/section could be identified |
| K | Field completeness | 1.0 if the field is fully populated (e.g., a list field has ≥1 item, a scalar field is a real sentence, not a stub); 0.5 if partially populated; 0.0 if empty/null |

This keeps every signal computable from data already produced by the
pipeline — no extra LLM calls, no re-sampling.

## Thresholds and review routing

| Score | Level | Behavior |
|---|---|---|
| ≥ 0.75 | HIGH | Automatically accepted, shown with a green badge |
| 0.45–0.749 | MEDIUM | Shown with a yellow badge and a "review suggested" note; not blocked |
| < 0.45 | LOW | `review_required = true`; surfaced in the Review page, yellow/red badge, must be Accepted/Edited/Rejected before counted in analytics as "confirmed" |

## Output shape (per extraction item)

```json
{
  "score": 0.91,
  "level": "HIGH",
  "signals": {
    "schema_validity": 1.0,
    "evidence_strength": 0.9,
    "source_relevance": 1.0,
    "completeness": 0.8
  },
  "review_required": false
}
```

## UI representation

Confidence is shown as a colored badge (green/yellow/red) next to every
extracted field/item, with a hover/click breakdown showing the four signal
values — never just the final number with no explanation, since the score
must remain explainable per the product principle.

## Known limitations (must be documented, not hidden)

- The score reflects extraction quality signals, not ground-truth accuracy;
  a fluent, well-evidenced but factually wrong claim can still score HIGH.
- Evidence-strength similarity is text-matching, not semantic verification;
  a superficially similar but semantically different passage can inflate `E`.
- No cross-paper or cross-run consistency checking is performed in the MVP
  (explicitly deferred, see rejected "K = resampling" approach above).

## Testing requirements

- Unit test the pure `calculate_confidence()` function against fixed input
  signal combinations, asserting exact score and level for each threshold
  boundary (0.449, 0.45, 0.749, 0.75).
- The zero-evidence routing rule remains an unresolved product/architecture
  decision. The weighted formula can produce up to 0.60 when `E=0`, which is
  MEDIUM. Do not implement the confidence engine or a special zero-evidence
  override until the project owner resolves whether the weighted score stands
  or missing evidence forces LOW. Preserve evidence presence, page/section
  location, and match metadata so the decision can be made with pipeline data.

## Deviation Log
(No formula, weights, or thresholds changed. The zero-evidence routing
decision remains unresolved at the project owner's direction, 2026-09-27.)
