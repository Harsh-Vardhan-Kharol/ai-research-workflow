# Agent Instructions

You are an AI coding agent implementing ResearchFlow AI from this context
package. Follow these rules exactly.

## 1. How to read this package
Read in the order given in `README.md`. Do not start writing code before
reading `PROJECT_OVERVIEW.md`, `REQUIREMENTS.md`, `SYSTEM_ARCHITECTURE.md`,
and `DATABASE_SCHEMA.md` at minimum.

## 2. Authoritative files
See the table in `README.md`. On any conflict between two documents, the
authoritative one for that domain wins. Note the conflict and its
resolution in the losing document's `## Deviation Log` section (add one if
missing).

## 3. Resolving ambiguity
If a requirement is ambiguous but resolvable using the principles in
`PROJECT_OVERVIEW.md` (AI only where semantic interpretation is needed;
everything else deterministic) and the priority order in `REQUIREMENTS.md`
(P0 before P1 before P2), resolve it yourself and document the decision
inline in the relevant file's Deviation Log. Only stop and ask the human
operator when a decision is genuinely unresolvable without running the
system (see `CONFIDENCE_SYSTEM.md`'s open zero-evidence question as an
example of exactly this kind of decision).

## 4. What must not change without explicit justification
- The AI/deterministic boundary in `AI_ARCHITECTURE.md`.
- The database schema's normalization (one extraction row per item).
- The confidence formula's weights (may be recalibrated, but the change and
  reason must be logged).
- The no-auth, no-queue-infra, no-vector-DB decisions — these were
  deliberate scope-protection choices, not omissions.

## 5. Maintaining architectural consistency
Before adding any new dependency, class, or table, check whether an
existing component in `SYSTEM_ARCHITECTURE.md` already owns that
responsibility. Extend, don't duplicate.

## 6. Testing
Follow `TESTING_STRATEGY.md`. No feature is complete without a passing
test per its acceptance criteria there.

## 7. Debugging
Use the structured log events defined in `ERROR_HANDLING.md` as your first
diagnostic signal — they exist precisely so failures are traceable to a
specific pipeline step without guessing.

## 8. Documenting changes
Any deviation from a spec in this package gets logged in that file's
`## Deviation Log` section (create one if it doesn't exist) with: what
changed, why, and the date/commit if available. Do not silently diverge.

## 9. Avoiding unnecessary complexity
Before adding any technology not listed in `TECH_STACK.md`, re-read its
"explicitly rejected" section — if what you're about to add resembles one
of those rejections, don't add it without updating that file first with a
real justification tied to a concrete blocker you hit (not convenience).

## 10. Handling dependencies
Pin versions in `requirements.txt`. Prefer the smallest dependency that
solves the problem (this is why `rapidfuzz` was chosen over building or
importing a heavier NLP similarity stack).

## 11. Handling errors
Follow the failure-mode matrix in `ERROR_HANDLING.md` exactly — same
detection method, same scoping (fail the smallest unit possible), same log
event name.

## 12. Handling AI output
Never let raw AI output reach the database. It must pass through: schema
validation -> evidence mapping -> confidence calculation, in that order,
per `SYSTEM_ARCHITECTURE.md`'s "Data flow contract" section.

## 13. Handling confidence calculations
Confidence is always computed by the pure deterministic function in
`CONFIDENCE_SYSTEM.md` — never ask the LLM for a confidence number and
never substitute it for the formula's signals.

## 14. Handling evidence
Evidence similarity is always computed against the actual stored page
text (`paper_pages`), never trusted as-is from the LLM's claim. See
`EVIDENCE_SYSTEM.md`.

## 15. Knowing when a feature is complete
Per `TESTING_STRATEGY.md`'s acceptance criteria section — tested, reachable
end-to-end, failure paths covered, docs in sync.

## 16. Reporting completed work
State plainly what was built, what tests cover it, and which requirement
ID(s) from `REQUIREMENTS.md` it satisfies. Do not claim a feature "works"
without a passing test demonstrating it.

## 17. Reporting unresolved problems
If you hit a genuine blocker (e.g., a provider's structured-output mode
behaves differently than documented), report it explicitly rather than
silently working around it in a way that changes the architecture — update
the relevant file's Deviation Log first, then proceed.

## 18. Priority discipline
Never build a P1 or P2 feature (per `REQUIREMENTS.md`) while any P0 item is
incomplete or broken. The Days 11–12 checkpoint in `DEVELOPMENT_ROADMAP.md`
is a hard gate.
