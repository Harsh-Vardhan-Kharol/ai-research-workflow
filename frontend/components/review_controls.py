"""Validated review form that submits decisions to FastAPI."""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

MAX_REVIEWED_VALUE_LENGTH = 12000
MAX_REVIEW_COMMENT_LENGTH = 2000


def validate_edit(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Edited value cannot be empty.")
    if len(cleaned) > MAX_REVIEWED_VALUE_LENGTH:
        raise ValueError("Edited value must be 12,000 characters or fewer.")
    return cleaned


def validate_comment(value: str) -> str | None:
    cleaned = value.strip()
    if len(cleaned) > MAX_REVIEW_COMMENT_LENGTH:
        raise ValueError("Comment must be 2,000 characters or fewer.")
    return cleaned or None


def render_review_controls(
    item: dict[str, Any],
    submit: Callable[..., dict[str, Any]],
    refreshed: Callable[[int], dict[str, Any]],
) -> None:
    if item.get("status") != "PENDING_REVIEW":
        st.caption("This extraction has already been reviewed.")
        return

    extraction_id = int(item["id"])
    comment = st.text_input(
        "Reviewer comment (optional)", max_chars=MAX_REVIEW_COMMENT_LENGTH,
        key=f"comment-{extraction_id}",
    )
    left, right = st.columns(2)
    if left.button("Accept", key=f"accept-{extraction_id}"):
        _submit("ACCEPT", extraction_id, submit, refreshed, comment=comment)
    if right.button("Reject", key=f"reject-{extraction_id}"):
        _submit("REJECT", extraction_id, submit, refreshed, comment=comment)
    with st.form(f"edit-form-{extraction_id}"):
        revised = st.text_area(
            "Reviewer-edited value", value=item.get("field_value", ""),
            key=f"edited-{extraction_id}", height=120,
            max_chars=MAX_REVIEWED_VALUE_LENGTH,
        )
        submitted = st.form_submit_button("Save edit")
    if submitted:
        try:
            cleaned = validate_edit(revised)
            cleaned_comment = validate_comment(comment)
        except ValueError as exc:
            st.error(str(exc))
            return
        _submit(
            "EDIT", extraction_id, submit, refreshed,
            reviewed_value=cleaned, comment=cleaned_comment,
        )


def _submit(
    action: str,
    extraction_id: int,
    submit: Callable[..., dict[str, Any]],
    refreshed: Callable[[int], dict[str, Any]],
    **kwargs: Any,
) -> None:
    try:
        submit(extraction_id, action, **kwargs)
        current = refreshed(extraction_id)
    except Exception as exc:
        # The app converts API failures into safe, user-readable exceptions.
        from frontend.api_client import ApiClientError

        if isinstance(exc, ApiClientError) and exc.status_code == 409:
            st.session_state[f"review-message-{extraction_id}"] = str(exc)
            try:
                refreshed(extraction_id)
            except ApiClientError as refresh_error:
                st.error(str(refresh_error))
            st.rerun()
        st.error(str(exc))
        return
    st.session_state[f"review-refresh-{extraction_id}"] = current
    st.success(current.get("status", f"{action}ED"))
    st.rerun()
