"""Pure transformations and Streamlit rendering for extraction items."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import streamlit as st


def group_extractions(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get("group_name") or "other")].append(item)
    return dict(grouped)


def render_extraction_identity(item: dict[str, Any]) -> None:
    st.markdown(f"**{item.get('field_name', 'Extraction')}** · `{item.get('status', 'UNKNOWN')}`")
    st.write(item.get("field_value") or "No extracted value.")
    if item.get("review"):
        review = item["review"]
        st.caption(f"Human decision: {review.get('review_status', item.get('status'))}")
        if review.get("reviewed_value") is not None:
            st.markdown("**Reviewer-edited value**")
            st.write(review["reviewed_value"])

