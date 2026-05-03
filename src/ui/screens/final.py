"""Final state — post-approval, pre/post-push.

Shows the matrix in read-only form, the generated PDF download button,
the full audit log, and a 'Push to Archive' button (Approver only) that
flips the record into the archive table.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from .. import api_client
from ..components import audit_log as audit_log_component
from . import matrix as matrix_screen


def render() -> None:
    matrix_screen._render_header()
    matrix_screen._render_matrices()

    st.divider()

    pdf_path = st.session_state.approve_pdf_path
    if pdf_path and Path(pdf_path).exists():
        with open(pdf_path, "rb") as f:
            st.download_button(
                "Download final PDF",
                f.read(),
                file_name=Path(pdf_path).name,
                mime="application/pdf",
                type="primary",
            )

    status = st.session_state.eval_status
    if status == "approved" and st.session_state.role == "Approver":
        if st.button("Push to Archive", type="primary"):
            with st.spinner("Snapshotting + pushing to archive..."):
                try:
                    result = api_client.push(
                        eval_id=st.session_state.eval_id,
                        actor_id=st.session_state.actor_id,
                    )
                except Exception as e:
                    st.error(f"Push failed: {e}")
                    return
            st.session_state.eval_status = "complete_and_pushed"
            st.session_state.archive_id = result["archive_id"]
            st.success(f"Pushed. Archive ID: {result['archive_id']}")
            st.rerun()

    if status == "complete_and_pushed":
        st.success(
            f"Evaluation closed. Archive ID: `{st.session_state.archive_id}`. "
            "The record now lives in the `archive` table."
        )

    st.divider()
    st.subheader("Full Audit Log")
    audit_log_component.render_inline(st.session_state.eval_id)
