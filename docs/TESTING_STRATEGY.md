# Testing Strategy

Phase 8 tests the frontend HTTP client's successful response parsing, safe
error conversion and review request payload, plus edit validation and
extraction grouping helpers. Phase 9 adds deterministic comparison tests for
normalization, READY/selection validation, frequencies and source traceability,
pairwise differences, missing fields, patterns, and unavailable limitations.
API tests cover the comparison schema and error envelope; frontend tests cover
request construction, response validation, and traceable render transformations.
Streamlit browser rendering is not asserted.

Phase 10 tests the explicit limitations/future-work prompt constraints and
strict Claim schemas, the shared extraction/evidence/confidence persistence
path, existing review actions for these groups, deterministic recurrence,
concentration/sparsity/coverage candidates, configurable thresholds, traceable
candidate records, API compatibility, and frontend candidate transformations.
Analytics fixtures are synthetic and make no external or LLM gap-generation
calls.

## Unit tests (`tests/unit/`)

| Subsystem | Cases | Acceptance criteria |
|---|---|---|
| PDF parsing | valid PDF, corrupted PDF, empty-text PDF | Correct page count/text for valid; correct FAILED reason for the other two |
| Section detection | standard/variant headings, numbering, capitalization, missing sections, multi-page spans, references, malformed whitespace, body prose, no headings | Correct page-aware content boundaries; graceful whole-document fallback when nothing is detected |
| Schema validation | valid payload, missing required field, wrong type, null-for-insufficient-evidence | Valid passes; each invalid case rejected with a specific, testable error |
| Evidence matching | exact, normalized whitespace, punctuation, partial, missing source, no match, invalid/missing page, multiple candidates, section/page consistency | Similarity scores fall in expected bands; invalid/missing page triggers fallback; proposed page/section are not trusted as matched location |
| Confidence calculation | all-strong/all-weak/mixed signals; boundary values immediately around 0.45 and 0.75; MATCHED/WEAK/UNAVAILABLE/FAILED/missing evidence; invalid values | Exact formula and level; zero/missing/weak/failed evidence routing independently requires review; no invalid value produces a score |
| Database repository | insert/read/update/delete for every table, cascade delete | Cascades verified by asserting child rows are gone after parent delete |
| Analytics | frequency counts against a fixture set of extractions | Counts match hand-computed expected values |
| Phase 9 comparison | normalization, selection, frequencies, pairwise differences, missing fields, patterns, and traceability | Deterministic results retain original values, confidence/review metadata, and source paper/extraction IDs |
| Phase 10 gap analytics | limitation/future-work groups, recurring values, concentration, sparse dimensions, method/dataset co-occurrence, thresholds, and candidate traceability | Claims use existing validation/evidence/confidence/review flow; candidates remain selected-literature-scoped and machine-traceable |

## Integration tests (`tests/integration/`)

- PDF -> parser -> section detection -> database: assert page text and
  correctly bounded `paper_sections` rows persist together in the pipeline.
- PDF -> parser -> extraction (AI calls mocked to return fixed structured
  output) -> database: assert correct rows land in `extractions`.
- validated extraction -> extraction rows -> stored page lookup -> evidence
  mapping -> database: assert proposed provenance remains separate from the
  matched page passage and evidence status/score are deterministic.
- Validated extraction -> evidence mapping -> confidence scoring -> SQLite ->
  extraction API: assert deterministic score/signals/review routing persist and
  paper reaches `READY` without live model calls.
- Pending extraction -> Accept/Edit/Reject review API -> SQLite -> extraction
  GET: assert terminal item state, one review record, immutable AI value,
  reviewed value/comment/timestamp, and unchanged paper status. Include
  invalid input, duplicate review, and transaction rollback cases.
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
