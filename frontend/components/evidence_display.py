"""Display AI source proposals separately from independently matched evidence."""

from typing import Any
import streamlit as st


def render_evidence(item: dict[str, Any]) -> None:
    st.markdown("**AI-proposed source**")
    proposal = item.get("proposed_source_text")
    st.write(proposal if proposal else "No source passage proposed by the AI.")
    evidence = item.get("evidence")
    if not evidence:
        st.info("Evidence unavailable.")
        return
    st.markdown(f"**Evidence match: {evidence.get('match_status', 'UNKNOWN')}**")
    details = []
    if evidence.get("page_number") is not None:
        details.append(f"Page {evidence['page_number']}")
    if evidence.get("section_name"):
        details.append(f"Section: {evidence['section_name']}")
    if details:
        st.caption(" · ".join(details))
    if evidence.get("evidence_score") is not None:
        st.caption(f"Evidence score: {evidence['evidence_score']:.3f}")
    if evidence.get("matched_source_text"):
        st.markdown("**Matched passage**")
        st.info(evidence["matched_source_text"])
    else:
        st.write("No matched passage is available.")
    if evidence.get("failure_code"):
        st.caption(f"Evidence detail: {evidence['failure_code']}")
    if evidence.get("match_status") == "MATCHED":
        st.caption("MATCHED indicates traceability to paper text, not factual correctness.")
