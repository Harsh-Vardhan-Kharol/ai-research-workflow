# ResearchFlow AI — Project Context Package

This directory is the implementation contract for ResearchFlow AI, an evidence-backed
research-paper extraction and analysis system. It is written for an AI coding agent
(Claude Code, Cursor, Windsurf, Codex, etc.) that will build the system.

## Read order (first pass, before writing any code)

1. `PROJECT_OVERVIEW.md` — what this is and isn't
2. `REQUIREMENTS.md` — MVP scope, demo-safe scope, out-of-scope
3. `SYSTEM_ARCHITECTURE.md` — components and data flow
4. `DATABASE_SCHEMA.md` — authoritative data model
5. `AI_ARCHITECTURE.md` — extraction service design
6. `CONFIDENCE_SYSTEM.md` and `EVIDENCE_SYSTEM.md`
7. `API_SPECIFICATION.md`
8. `WORKFLOW_SPEC.md` — end-to-end pipeline with failure modes
9. `UI_UX_SPECIFICATION.md`
10. `SECURITY.md`, `ERROR_HANDLING.md`
11. `TESTING_STRATEGY.md`
12. `DEVELOPMENT_ROADMAP.md`, `ENVIRONMENT_SETUP.md`, `DEMO_GUIDE.md`

`AGENT_INSTRUCTIONS.md` should be read last, immediately before writing code — it governs
*how* to work through the rest of this package.

## Authoritative documents (tie-breakers on conflict)

| Domain | Authoritative file |
|---|---|
| Product requirements / scope | `REQUIREMENTS.md` |
| Architecture / data flow | `SYSTEM_ARCHITECTURE.md` |
| Database schema | `DATABASE_SCHEMA.md` |
| API contracts | `API_SPECIFICATION.md` |
| AI extraction behavior | `AI_ARCHITECTURE.md` |
| Confidence scoring | `CONFIDENCE_SYSTEM.md` |
| Evidence handling | `EVIDENCE_SYSTEM.md` |
| UI behavior | `UI_UX_SPECIFICATION.md` |
| Security rules | `SECURITY.md` |
| Testing requirements | `TESTING_STRATEGY.md` |

If two documents disagree, the table above decides which one wins. Any deviation from
these files must be noted in the file itself (a `## Deviation Log` section) with a reason.

## What "done" means for the MVP

The **Minimum Demo-Safe Version** defined in `REQUIREMENTS.md` is the floor that must
never be broken while building anything else. Everything past it (limitations/future-work
extraction, richer analytics, review UI polish) is additive and can slip without
threatening the demo.
