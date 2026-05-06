"""Matrix screen — read-only Technical + Commercial matrices, no actions.

Used when the Preparer is viewing an eval that the Reviewer hasn't acted
on yet, or any role just wants to see the current matrices without
triggering anything.
"""

from __future__ import annotations

import streamlit as st

from ..components.matrix_table import render_matrix


def render() -> None:
    _render_header()
    _render_matrices()
    st.info(
        "Read-only view. Switch role in the sidebar to Reviewer to accept / reject this evaluation."
    )


def _render_header() -> None:
    metadata = st.session_state.metadata or {}
    st.title("Evaluation Matrix")
    st.markdown(
        f"**Tender:** `{metadata.get('tender_number', '?')}` &nbsp;|&nbsp; "
        f"**Iteration:** `{st.session_state.iteration or '-'}` &nbsp;|&nbsp; "
        f"**Status:** `{st.session_state.eval_status or '-'}`"
    )


def _render_matrices() -> None:
    technical = st.session_state.technical
    commercial = st.session_state.commercial
    if not technical:
        st.warning("Evaluation results not loaded. Switch back to Preparer + Confirm.")
        return

    tab_tech, tab_comm = st.tabs(["Technical Evaluation", "Commercial Evaluation"])
    with tab_tech:
        st.caption(
            f"Qualified: {technical['qualified_count']} / {technical['total_count']}"
            f" — {technical.get('summary_remarks', '')}"
        )
        render_matrix(
            technical["rubric"]["technical_criteria"],
            technical["vendor_evaluations"],
        )
    with tab_comm:
        if commercial and commercial.get("rubric"):
            st.caption(f"Qualified: {commercial['qualified_count']} / {commercial['total_count']}")
            render_matrix(
                commercial["rubric"]["commercial_criteria"],
                commercial["vendor_evaluations"],
            )
        else:
            st.info("No commercial evaluation generated for this tender.")
