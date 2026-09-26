# Demo Guide

Use this as the literal checkpoint script for "the Demo-Safe Core works."

1. Upload 2–3 sample papers (from `data/sample_papers/`) via the Upload page.
2. Show each moving through status (UPLOADED -> ... -> READY) on the
   Papers page.
3. Open one processed paper's Detail page.
4. Show its structured extractions grouped by field, each with a
   confidence badge.
5. Click a HIGH-confidence extraction; show its evidence panel (page,
   section, matched passage).
6. Select 2–3 papers on the Comparison page; show the field-by-field table.
7. Show basic frequency analytics (methods/datasets/metrics) across the
   uploaded papers.
8. Find (or intentionally induce, e.g. via a low-quality sample paper) a
   LOW-confidence extraction; open it on the Review page.
9. Perform an Edit action with a reviewer comment; show the extraction's
   value and status update, and that the original value is still retrievable
   via the review record.
10. Re-open the Paper Detail page and confirm the edited value now displays
    with updated status.

If any step in this script fails, that is a P0 regression and takes
priority over any P1 work in progress.
