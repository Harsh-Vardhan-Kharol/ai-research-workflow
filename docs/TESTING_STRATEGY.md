# Testing Strategy

## Unit tests (`tests/unit/`)

| Subsystem | Cases | Acceptance criteria |
|---|---|---|
| PDF parsing | valid PDF, corrupted PDF, empty-text PDF | Correct page count/text for valid; correct FAILED reason for the other two |
| Section detection | standard/variant headings, numbering, capitalization, missing sections, multi-page spans, references, malformed whitespace, body prose, no headings | Correct page-aware content boundaries; graceful whole-document fallback when nothing is detected |
| Schema validation | valid payload, missing required field, wrong type, null-for-insufficient-evidence | Valid passes; each invalid case rejected with a specific, testable error |
| Evidence matching | exact match, paraphrased match, no match, wrong page cited | Similarity scores fall in expected bands; wrong-page triggers fallback search |
| Confidence calculation | boundary values at 0.449/0.45/0.749/0.75; zero-evidence case | Exact score and level per the formula in `CONFIDENCE_SYSTEM.md`; the zero-evidence-forced-LOW question from that file resolved and tested one way or the other |
| Database repository | insert/read/update/delete for every table, cascade delete | Cascades verified by asserting child rows are gone after parent delete |
| Analytics | frequency counts against a fixture set of extractions | Counts match hand-computed expected values |

## Integration tests (`tests/integration/`)

- PDF -> parser -> section detection -> database: assert page text and
  correctly bounded `paper_sections` rows persist together in the pipeline.
- PDF -> parser -> extraction (AI calls mocked to return fixed structured
  output) -> database: assert correct rows land in `extractions`.
- extraction -> evidence -> confidence -> database: assert the full
  deterministic chain produces the expected confidence object end-to-end
  given a fixed extraction + fixed page text fixture.
- Failure-path integration: corrupted PDF end-to-end results in
  `status=FAILED` with the correct `failure_reason`.

## End-to-end tests (`tests/e2e/`)

Upload a real (small, sample) paper -> process -> poll status to READY ->
fetch extractions -> fetch evidence for one item -> submit a review action
-> fetch analytics -> run a 2-paper comparison. Assert each step returns
expected shapes per `API_SPECIFICATION.md`. AI calls should be mockable via
an env flag (`AI_PROVIDER=mock`) so e2e tests don't require a live API key
or incur cost in CI/local test runs.

## Acceptance criteria for "a feature is complete"

A feature is complete only when: (1) it has at least one unit test and, if
it touches more than one component, at least one integration test; (2) it
is reachable through the actual API/UI, not just tested in isolation; (3)
failure paths relevant to it are covered per `ERROR_HANDLING.md`; (4) it is
reflected accurately in this documentation set (no doc/code drift).

Never report a feature as "working" without a passing test demonstrating
it — see `AGENT_INSTRUCTIONS.md`.
