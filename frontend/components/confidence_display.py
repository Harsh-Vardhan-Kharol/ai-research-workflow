"""Presentation for backend-calculated extraction confidence."""

from typing import Any
import streamlit as st


def render_confidence(item: dict[str, Any]) -> None:
    score = item.get("confidence_score")
    level = item.get("confidence_level")
    if score is None:
        st.info("Confidence has not been calculated yet.")
    else:
        st.markdown(f"**Extraction confidence:** {score:.3f} · **{level or 'UNRATED'}**")
    st.caption(f"Human review decision: {item.get('status', 'UNKNOWN')}")
    st.caption(f"Review required: {'Yes' if item.get('review_required') else 'No'}")
    reasons = item.get("review_reasons") or []
    if reasons:
        st.markdown("**Review reasons**")
        for reason in reasons:
            st.markdown(f"- `{reason}`")
    signals = item.get("confidence_signals")
    if isinstance(signals, dict) and signals:
        st.caption("Confidence signals")
        st.json(signals, expanded=False)
