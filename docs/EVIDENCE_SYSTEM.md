# Evidence System

## Data model

```json
{
  "field": "methodology",
  "value": "Transformer-based architecture",
  "page": 5,
  "section": "Methodology",
  "source_text": "We propose a transformer-based architecture...",
  "evidence_score": 0.87
}
```

Stored in the `evidence` table, one row per extraction item (see
`DATABASE_SCHEMA.md`), foreign-keyed to `extractions.id`.

## Extraction process

1. During AI extraction, the model is required to return, per non-null
   field, a claimed `source_text` (the passage it believes supports the
   value) and, if identifiable, a `page` and `section`.
2. The Evidence Mapper (deterministic code) takes that claimed passage and:
   a. Looks up the actual stored text of the cited page (from
      `paper_pages`).
   b. Computes a similarity ratio (`rapidfuzz.fuzz.partial_ratio`, 0–100,
      normalized to 0–1) between the claimed passage and the actual page
      text.
   c. If the claimed page is missing/invalid, searches all pages for the
      best-matching passage instead (fallback), and marks
      `page_corrected: true`.
3. The resulting `evidence_score` feeds directly into the confidence
   system's `E` signal.

## Validation rules

- `evidence_score` below `MIN_EVIDENCE_THRESHOLD` (default 0.35) still gets
  stored (never silently discarded — the reviewer should be able to see
  that the AI's cited evidence didn't actually match), but contributes
  `E = 0` to confidence.
- An extraction item with a non-null value but zero evidence rows is valid
  (the AI may have returned no `source_text`) and is stored with
  `evidence_score = 0`.

## Limitations of evidence matching (must be surfaced in the UI, not hidden)

- Matching a passage confirms **traceability**, not **factual correctness**.
  A high evidence score means "this text really exists in the paper near
  where the AI said it does," not "this claim is true."
- Similarity matching can be fooled by superficially similar but
  semantically different text (e.g., a limitations section restating a
  method described elsewhere).
- Multi-sentence or non-contiguous evidence (a claim supported by combining
  two separate paragraphs) will score lower than a single-passage match,
  even when the underlying extraction is correct.

## How evidence is displayed

On the paper detail page, each extracted field/item shows its confidence
badge; clicking it opens an evidence panel showing: page number, section
name, and the matched passage with the claimed value highlighted. If
evidence_score is below threshold, show a visible "evidence not strongly
matched" note rather than presenting it as if it were verified.

## How evidence links to extracted claims

`evidence.extraction_id -> extractions.id` (one-to-one for MVP: each
extraction item has at most one evidence record, since list fields are
already split one-row-per-item in `extractions`). If a future version
needs multiple supporting passages per claim, that is a schema change to
document, not to build speculatively now.
