"""Reviewer screen — matrix + Accept + Reject-with-feedback."""

from __future__ import annotations

import streamlit as st

from .. import api_client
from . import matrix as matrix_screen


def render() -> None:
    matrix_screen._render_header()
    matrix_screen._render_matrices()

    st.divider()
    st.subheader("Reviewer Decision")

    feedback = st.text_area(
        "Feedback (required if rejecting)",
        placeholder="e.g., 'Re-check vendor 3 turnover - the avg looks off compared to balance sheets.'",
        key="reviewer_feedback",
    )

    cols = st.columns([1, 1, 4])
    accept_clicked = cols[0].button("Accept", type="primary", use_container_width=True)
    reject_clicked = cols[1].button("Reject + Re-evaluate", use_container_width=True)

    if accept_clicked:
        with st.spinner("Recording acceptance..."):
            try:
                api_client.review_accept(
                    eval_id=st.session_state.eval_id,
                    actor_id=st.session_state.actor_id,
                )
            except Exception as e:
                st.error(f"Accept failed: {e}")
                return
        st.session_state.eval_status = "review_accepted"
        st.success("Accepted. Switch role to Approver to sign off.")
        st.rerun()

    if reject_clicked:
        if not feedback.strip():
            st.error("Please enter feedback before rejecting.")
            return
        with st.spinner(
            "Re-running CriteriaExtractionAgent + VendorEvaluationAgent with your feedback... "
            "(another minute or two)"
        ):
            try:
                result = api_client.review_reject(
                    eval_id=st.session_state.eval_id,
                    actor_id=st.session_state.actor_id,
                    feedback_text=feedback,
                )
            except Exception as e:
                st.error(f"Reject failed: {e}")
                return
        st.session_state.iteration = result["iteration"]
        st.session_state.technical = result["technical"]
        st.session_state.commercial = result["commercial"]
        st.session_state.eval_status = "eval_ready"
        st.success(f"Re-evaluated. Iteration is now {result['iteration']}.")
        st.rerun()
