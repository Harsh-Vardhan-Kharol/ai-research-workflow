# Evidence System

## Data model

```json
{
  "field": "methodology",
  "value": "Transformer-based architecture",
  "proposed_page": 5,
  "proposed_section": "Methodology",
  "proposed_source_text": "We propose a transformer-based architecture...",
  "page": 5,
  "section": "Methodology",
  "source_text": "We propose a transformer-based architecture...",
  "evidence_score": 0.87,
  "match_status": "MATCHED"
}
```

Stored in the `evidence` table, one row per extraction item (see
`DATABASE_SCHEMA.md`), foreign-keyed to `extractions.id`.

## Extraction process

1. During AI extraction, the model is required to return, per non-null
   field, a claimed `source_text` (the passage it believes supports the
   value) and, if identifiable, a `page` and `section`.
2. The deterministic Evidence Mapper independently loads actual stored
   `paper_pages` text and compares the proposal with it. It never accepts an
   AI page or quote as proof by itself.
   a. Normalize Unicode, case, punctuation, and whitespace for comparison.
   b. Run `rapidfuzz.fuzz.partial_ratio` against the cited page when that page
      exists. The alignment variant returns the exact matched span for display.
   c. If the proposed page is missing or not present in `paper_pages`, search
      all stored pages and select the highest-scoring passage, breaking ties
      by lower page number. Mark `page_corrected: true` for this fallback.
   d. Resolve a section only when the matched passage occurs in persisted
      `paper_sections.content` whose page range includes the matched page. Do
      not copy the AI-proposed section into the verified section field.
3. Normalize the ratio to [0, 1]. Persist the independently found span and
   score; evidence strength is an input to the later confidence phase only.

## Validation rules

- `evidence_score` below `MIN_EVIDENCE_THRESHOLD` (default 0.35) still gets
  stored (never silently discarded — the reviewer should be able to see
  that the AI's cited evidence didn't actually match), but contributes
  `E = 0` to confidence.
- Every non-null extraction item gets one evidence row in this implementation,
  including `UNAVAILABLE` when no proposal or candidate text exists. The
  unavailable record has score 0, null actual page/section, and empty actual
  `source_text`; the original proposal remains on the extraction row.
- A source passage that matches below the threshold remains stored with its
  actual passage/page and `match_status = WEAK`.

## Evidence states

The evidence specification defines scores and a threshold but no state names.
Phase 5 adds these explicit traceability states:

| State | Meaning |
|---|---|
| `MATCHED` | Score meets `MIN_EVIDENCE_THRESHOLD`; a passage was found in stored page text. This does not confirm claim truth. |
| `WEAK` | A passage candidate was found, but its score is below the threshold. |
| `UNAVAILABLE` | Source was absent, pages were unavailable, or no passage candidate was found. |
| `FAILED` | Mapping could not be evaluated because source data was malformed or a mapping operation failed. |

These states describe traceability only. They do not replace `evidence_score`
or implement confidence/review routing.

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
