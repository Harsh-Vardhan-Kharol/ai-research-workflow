# UI/UX Specification (Streamlit)

## Why Streamlit remains appropriate

The MVP needs a dashboard, a detail view with confidence badges, an evidence
viewer, a comparison table, basic charts, and simple review controls —
none of which require highly custom interaction patterns, real-time
collaboration, or a design system beyond "clear and functional." Streamlit
covers all of this natively (via `st.dataframe`, `st.expander`,
`st.columns`, `st.plotly_chart` or built-in charting, and simple
button/form widgets) with far less build time than a React frontend, which
would require a separate API-contract layer, build tooling, and days of
component work with no corresponding functional gain for this project's
scope. React would only be justified by a real requirement for rich
custom interactivity or a production multi-user product — neither applies
here. Recommend Streamlit; document React as a legitimate future upgrade
only if the project continues past this MVP.

## Pages

### Upload
Multi-file uploader (PDF only) sends selected files to `/papers/upload-batch`,
shows per-file success or validation errors inline, and leaves uploaded papers
ready to process from the Papers page.

### AI configuration
The sidebar provides a password-style API-key placeholder. After saving, only
a saved status is shown; the key is retained in Streamlit session memory and is
not written to the database or displayed again. Hosted-provider execution
still requires the backend provider settings (`AI_MODEL_NAME` and
`AI_BASE_URL`).

### Papers (list)
Table of papers with status badges; click-through to Paper Detail.

### Paper Detail
- Header: title, authors, year (from metadata extraction).
- Grouped extraction cards per field_name, each showing value(s) and a
  colored confidence badge (green/yellow/red per `CONFIDENCE_SYSTEM.md`).
- Clicking a card opens an evidence panel (page, section, matched passage,
  with a visible note if evidence_score is below threshold).

### Comparison
Multi-select of 2–3 papers; renders a field-by-field comparison table with
confidence badges per cell.

### Analytics
Simple bar charts for method/dataset/metric frequency; computed via the
live analytics endpoints.

### Review
List of extractions with `status = PENDING_REVIEW`, each with Accept / Edit
/ Reject controls; Edit opens a text input pre-filled with the original
value.

## Confidence badge design

- Green = HIGH (≥0.75), Yellow = MEDIUM (0.45–0.749), Red = LOW (<0.45).
- Badge is always clickable/hoverable to reveal the four underlying signal
  values — never shown as a bare number with no explanation.

## Evidence viewer

Always shows: page number, section name, the matched passage (highlighting
the claimed value if it appears verbatim), and the evidence_score. If the
score is below `MIN_EVIDENCE_THRESHOLD`, show a visible caption:
"Evidence not strongly matched to source text."
