"""Approver screen — matrix + Approve (generates final PDF)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from .. import api_client
from . import matrix as matrix_screen


def render() -> None:
    matrix_screen._render_header()
    matrix_screen._render_matrices()

    st.divider()
    st.subheader("Approver Decision")

    cols = st.columns([1, 4])
    approve_clicked = cols[0].button("Approve", type="primary", use_container_width=True)

    if approve_clicked:
        with st.spinner("Approving and generating final PDF..."):
            try:
                result = api_client.approve(
                    eval_id=st.session_state.eval_id,
                    actor_id=st.session_state.actor_id,
                )
            except Exception as e:
                st.error(f"Approve failed: {e}")
                return
        st.session_state.eval_status = "approved"
        st.session_state.approve_pdf_path = result["pdf_path"]
        st.success("Approved. Final PDF generated.")
        st.rerun()
