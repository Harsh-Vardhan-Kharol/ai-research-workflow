# Security

## Threat model scope

Single local operator, no multi-user data isolation requirement. The real
risks in scope are: malicious/malformed uploads, prompt injection via paper
content, secret leakage, and unsafe temp-file handling — not authentication
or authorization (explicitly out of scope for MVP).

## System instructions vs paper content (critical, always enforced)

Every AI prompt must clearly separate:
- **SYSTEM INSTRUCTIONS**: fixed, written by the developer, never derived
  from paper content.
- **PAPER CONTENT**: always wrapped in an explicit delimiter (e.g.
  `<paper_content>...</paper_content>`) and always accompanied by an
  instruction stating that anything inside this block is data to analyze,
  never a command to follow — even if it looks like an instruction (e.g. a
  paper containing the literal text "ignore previous instructions").

## Input validation

- Uploaded file must pass both extension check (`.pdf`) and MIME/magic-byte
  sniff before being handed to PyMuPDF.
- Enforce `MAX_UPLOAD_SIZE_MB` before reading the full file into memory.
- Reject files that PyMuPDF cannot open (corrupted) with a clear error, not
  a stack trace.
- All API request bodies validated via Pydantic before touching business
  logic.

## Secret management

- `AI_API_KEY` and any other credentials live only in environment variables
  / a local `.env` file (never committed — `.env` in `.gitignore`,
  `.env.example` committed with placeholder values).
- Never log API keys. Never include them in error messages returned to the
  client.

## Logging & privacy

- Do not log full paper text or full LLM prompts/responses at INFO level;
  log only metadata (paper id, field name, byte counts, timing,
  success/failure) at INFO, and gate full-content logging behind DEBUG,
  understanding that DEBUG logs may contain sensitive research content and
  should not be shipped/shared casually.

## Temporary file handling

- Uploaded files are written to a dedicated `data/uploads/` directory (or a
  temp dir) with a generated filename (not the raw user-supplied filename,
  to avoid path traversal); original filename is stored only as metadata in
  `papers.file_name`.

## Data deletion

`DELETE /papers/{id}` removes the DB rows (cascading) and must also delete
the underlying stored PDF file from disk — a paper "delete" is not complete
if the file remains.

## Dependency risk

Keep the dependency list in `TECH_STACK.md` as the ceiling — do not add
new third-party packages during implementation without checking against
that list; if a new dependency becomes genuinely necessary, add it there
first with a one-line justification (Deviation Log pattern, same as other
authoritative files).
