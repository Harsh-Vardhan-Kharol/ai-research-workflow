"""ResearchFlow human review and paper inspection interface."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

# Streamlit executes this file as a script and may put only ``frontend/`` on
# sys.path. The frontend's absolute package imports need the repository root.
_REPOSITORY_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

import streamlit as st

from frontend.api_client import ApiClientError, ResearchFlowApi
from frontend.components.confidence_display import render_confidence
from frontend.components.evidence_display import render_evidence
from frontend.components.extraction_card import group_extractions, render_extraction_identity
from frontend.components.review_controls import render_review_controls
from frontend.components.comparison_view import frequency_rows, pairwise_rows, gap_candidate_rows


def api() -> ResearchFlowApi:
    return ResearchFlowApi()


def show_error(exc: ApiClientError) -> None:
    if exc.status_code == 404:
        st.warning(str(exc))
    else:
        st.error(str(exc))


def upload_page(client: ResearchFlowApi) -> None:
    st.header("Upload a paper")
    uploaded = st.file_uploader("Choose a research paper PDF", type=["pdf"])
    if uploaded and st.button("Upload PDF", type="primary"):
        try:
            result = client.upload_paper(uploaded.name, uploaded)
            st.success(f"Uploaded {result.get('file_name', uploaded.name)} · Paper #{result['id']} · {result['status']}")
            st.info("Open Papers and start processing when ready.")
        except ApiClientError as exc:
            show_error(exc)


def _paper_label(paper: dict[str, Any]) -> str:
    return f"#{paper['id']} · {paper.get('title') or paper.get('file_name') or 'Untitled paper'} · {paper.get('status', 'UNKNOWN')}"


def papers_page(client: ResearchFlowApi) -> None:
    st.header("Papers")
    top_left, top_right = st.columns([5, 1])
    top_left.caption("Paper processing state and extraction review state are tracked separately.")
    if top_right.button("Refresh", key="papers-refresh"):
        st.session_state.pop("selected-paper-id", None)
    try:
        with st.spinner("Loading papers..."):
            papers = client.list_papers()
    except ApiClientError as exc:
        show_error(exc)
        return
    if not papers:
        st.info("No papers available.")
        return

    by_id = {int(paper["id"]): paper for paper in papers}
    prior = st.session_state.get("selected-paper-id")
    default_id = prior if prior in by_id else int(papers[0]["id"])
    selected_id = st.selectbox(
        "Select paper", list(by_id), index=list(by_id).index(default_id),
        format_func=lambda paper_id: _paper_label(by_id[paper_id]),
    )
    st.session_state["selected-paper-id"] = selected_id
    paper = by_id[selected_id]
    st.markdown(f"### {paper.get('title') or paper.get('file_name', 'Untitled paper')}")
    st.caption(f"Paper ID: {selected_id} · Uploaded: {paper.get('created_at', 'Unavailable')}")
    status_col, review_col = st.columns(2)
    status_col.metric("Processing status", paper.get("status", "UNKNOWN"))
    review_col.metric("Pending reviews", paper.get("pending_review_count", 0))

    if paper.get("status") in {"UPLOADED", "FAILED"}:
        if st.button("Start processing" if paper.get("status") == "UPLOADED" else "Retry processing"):
            try:
                result = client.process_paper(selected_id)
                st.success(f"Processing started: {result.get('status', 'EXTRACTING_TEXT')}")
                st.rerun()
            except ApiClientError as exc:
                show_error(exc)
    _paper_detail(client, selected_id)


def _paper_detail(client: ResearchFlowApi, paper_id: int) -> None:
    try:
        with st.spinner("Loading paper details..."):
            detail = client.get_paper(paper_id)
            status = client.get_paper_status(paper_id)
            groups_response = client.get_extraction_groups(paper_id)
            items = client.get_extractions(paper_id)
    except ApiClientError as exc:
        show_error(exc)
        return
    st.divider()
    st.subheader("Paper information")
    st.caption(f"Status: {status.get('status', detail.get('status', 'UNKNOWN'))}")
    if status.get("failure_reason"):
        st.warning(f"Processing detail: {status['failure_reason']}")
    if detail.get("authors"):
        st.write(f"**Authors:** {detail['authors']}")
    if detail.get("publication_year"):
        st.write(f"**Publication year:** {detail['publication_year']}")
    if detail.get("abstract"):
        st.write(detail["abstract"])

    st.subheader("Extraction groups")
    group_states = {g.get("group_name"): g for g in groups_response.get("groups", [])}
    grouped = group_extractions(items)
    if not grouped and not group_states:
        st.info("No extraction data available.")
        return
    for group_name in dict.fromkeys([*group_states, *grouped]):
        state = group_states.get(group_name, {})
        with st.expander(f"{group_name.replace('_', ' ').title()} · {state.get('status', 'EXTRACTIONS')}", expanded=True):
            if state.get("status") == "FAILED":
                st.warning(f"This extraction group failed ({state.get('failure_code') or 'reason unavailable'}).")
            for item in grouped.get(group_name, []):
                _render_item(client, item, controls=False)
            if not grouped.get(group_name) and state.get("status") == "SUCCEEDED":
                st.caption("This group completed without non-empty extraction items.")


def _render_item(client: ResearchFlowApi, item: dict[str, Any], *, controls: bool) -> None:
    with st.container(border=True):
        message_key = f"review-message-{item.get('id')}"
        if message_key in st.session_state:
            st.warning(st.session_state.pop(message_key))
        render_extraction_identity(item)
        render_confidence(item)
        render_evidence(item)
        if controls:
            render_review_controls(item, client.review_extraction, client.get_extraction)


def review_page(client: ResearchFlowApi) -> None:
    st.header("Review queue")
    if st.button("Refresh review queue", key="review-refresh"):
        st.session_state.pop("review-refresh-trigger", None)
    try:
        with st.spinner("Loading papers..."):
            papers = client.list_papers()
        queue: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for paper in papers:
            with st.spinner(f"Loading extractions for paper #{paper['id']}..."):
                for item in client.get_extractions(int(paper["id"])):
                    if item.get("review_required") is True or item.get("status") == "PENDING_REVIEW":
                        queue.append((paper, item))
    except ApiClientError as exc:
        show_error(exc)
        return
    if not queue:
        st.info("No items currently require review.")
        return
    for paper, item in queue:
        title = paper.get("title") or paper.get("file_name") or f"Paper #{paper['id']}"
        st.markdown(f"### {title} · {item.get('group_name', '').replace('_', ' ').title()}")
        st.caption(f"Paper #{paper['id']} · Extraction #{item.get('id')} · {item.get('status')}")
        _render_item(client, item, controls=True)


def comparison_page(client: ResearchFlowApi) -> None:
    st.header("Multi-paper comparison")
    st.caption("Deterministic analysis of persisted structured extractions. Missing fields mean they were not extracted/reported in the structured record.")
    try:
        papers = [paper for paper in client.list_papers() if paper.get("status") == "READY"]
    except ApiClientError as exc:
        show_error(exc)
        return
    if not papers:
        st.info("No READY papers are available for comparison.")
        return
    by_id = {int(paper["id"]): paper for paper in papers}
    selected = st.multiselect(
        "Select at least two READY papers",
        list(by_id),
        format_func=lambda paper_id: _paper_label(by_id[paper_id]),
        key="comparison-paper-ids",
    )
    if st.button("Compare papers", type="primary", disabled=len(selected) < 2):
        try:
            st.session_state["comparison-result"] = client.compare_papers(selected)
        except ApiClientError as exc:
            show_error(exc)
            return
    comparison = st.session_state.get("comparison-result")
    if not comparison:
        return
    selected_papers = comparison.get("selected_papers", [])
    if [int(paper["id"]) for paper in selected_papers] != [int(pid) for pid in selected]:
        st.info("Run the comparison for the current paper selection to refresh these results.")
        return
    paper_map = {int(paper["id"]): paper for paper in selected_papers}
    st.subheader("Selected papers")
    st.dataframe(
        [{"Paper ID": p["id"], "Title": p.get("title") or p["file_name"], "Status": p["status"]}
         for p in selected_papers], hide_index=True, use_container_width=True,
    )
    labels = {
        "research_problem_objective": "Research problems and objectives",
        "methodology_models": "Methods and models",
        "datasets": "Datasets",
        "experimental_setup": "Experimental setup",
        "evaluation_metrics": "Evaluation metrics",
        "key_results": "Key results",
        "limitations": "Limitations",
        "future_work": "Future work",
    }
    st.subheader("Structured dimensions")
    for dimension in comparison.get("dimensions", []):
        label = labels.get(dimension["name"], dimension["name"].replace("_", " ").title())
        with st.expander(label, expanded=dimension["name"] in {"methodology_models", "datasets", "evaluation_metrics"}):
            if not dimension.get("available"):
                st.info("Unavailable: this dimension is not part of the persisted extraction schema.")
                continue
            rows = frequency_rows(dimension, paper_map)
            if not rows:
                st.caption("No values were extracted/reported in the selected structured records.")
                continue
            st.dataframe(
                [{key: value for key, value in row.items() if key != "Source records"}
                 for row in rows], hide_index=True, use_container_width=True,
            )
            for row in rows:
                st.markdown(f"**Sources for {row['Value']}**")
                st.json(row["Source records"])
    st.subheader("Differences")
    differences = pairwise_rows(comparison, paper_map)
    if differences:
        st.dataframe(differences, hide_index=True, use_container_width=True)
    else:
        st.caption("No paper-level values were available to compare.")
    st.subheader("Missing information")
    missing_rows = [
        {"Dimension": labels.get(item["dimension"], item["dimension"].replace("_", " ").title()),
         "Reported by": (f"{item['reported_by_count']}/{item['selected_paper_count']}"
                         if item["available"] else "Unavailable"),
         "Paper IDs not reported": item["paper_ids_not_reported"] if item["available"] else "Unavailable",
         "Available": item["available"]}
        for item in comparison.get("missing_information", [])
    ]
    st.dataframe(missing_rows, hide_index=True, use_container_width=True)
    st.subheader("Research patterns")
    patterns = comparison.get("patterns", [])
    if patterns:
        for pattern in patterns:
            st.write(f"- {pattern['message']} · Paper IDs: {', '.join(map(str, pattern['paper_ids']))}")
    else:
        st.caption("No deterministic pattern rules matched this selection.")

    for key, heading in (("limitations", "Limitations"), ("future_work", "Future Work")):
        summary = comparison.get(key, {})
        st.subheader(heading)
        if not summary.get("available"):
            st.info(f"{heading} extraction data is unavailable.")
            continue
        frequencies = summary.get("frequencies", [])
        repeated = [item for item in frequencies if item.get("count", 0) >= 2]
        if not repeated:
            st.caption(f"No repeated {heading.lower()} values across the selected papers.")
        for item in repeated:
            st.markdown(f"**{', '.join(item.get('original_values', []))}** · {item.get('count')} papers")
            st.write(f"Paper IDs: {', '.join(map(str, item.get('paper_ids', [])))}")
            st.json(item.get("sources", []))

    st.subheader("Potential Gap Candidates")
    candidates = comparison.get("gap_candidates", [])
    if not candidates:
        st.caption("No deterministic gap-candidate rules matched this selection.")
    for candidate, row in zip(candidates, gap_candidate_rows(candidates, paper_map)):
        with st.container(border=True):
            st.markdown(f"**Potential Gap Candidate · {candidate.get('title', 'Untitled')}**")
            st.caption(f"Type: {row['Type']} · Scope: {row['Scope']}")
            st.write(candidate.get("description", ""))
            st.markdown(f"**Basis:** {row['Basis']}")
            st.write(f"Supporting papers: {', '.join(row['Papers'])} · IDs {', '.join(map(str, row['Paper IDs']))}")
            st.write(f"Supporting extraction records: {', '.join(map(str, row['Extraction IDs']))}")
            st.json({"relevant_values": candidate.get("relevant_values", []), "sources": row["Sources"]})


def main() -> None:
    st.set_page_config(page_title="ResearchFlow AI", page_icon="📄", layout="wide")
    st.title("ResearchFlow AI")
    st.caption("Inspect extracted claims, their evidence, and the system's review signals.")
    client = api()
    page = st.sidebar.radio("Workspace", ["Papers", "Review queue", "Compare papers", "Upload"])
    if page == "Upload":
        upload_page(client)
    elif page == "Review queue":
        review_page(client)
    elif page == "Compare papers":
        comparison_page(client)
    else:
        papers_page(client)


if __name__ == "__main__":
    main()
