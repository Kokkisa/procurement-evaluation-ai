"""Upload screen — visible when no eval is in session and role is Preparer."""

from __future__ import annotations

import streamlit as st

from .. import api_client


def render() -> None:
    st.title("Procurement Evaluation AI")
    st.caption(
        "Upload a tender PDF and one or more vendor submissions (ZIP archives or "
        "individual PDFs). The system will extract metadata, ask you to confirm, "
        "then run the per-vendor evaluation."
    )

    if st.session_state.role != "Preparer":
        st.warning(
            "Only the Preparer role can start a new evaluation. Switch role in the sidebar."
        )
        return

    with st.form("upload-form", clear_on_submit=False):
        tender = st.file_uploader(
            "Tender PDF", type=["pdf"], accept_multiple_files=False, key="ul_tender"
        )
        vendors = st.file_uploader(
            "Vendor submissions (ZIP or PDF, one per vendor)",
            type=["zip", "pdf"],
            accept_multiple_files=True,
            key="ul_vendors",
        )
        submitted = st.form_submit_button("Start Evaluation", type="primary")

    if not submitted:
        return

    if tender is None:
        st.error("Please upload a tender PDF.")
        return
    if not vendors:
        st.error("Please upload at least one vendor submission.")
        return

    with st.spinner("Uploading + extracting metadata (one LLM call)..."):
        try:
            result = api_client.ingest(
                actor_id=st.session_state.actor_id,
                tender=(tender.name, tender.getvalue()),
                vendor_files=[(v.name, v.getvalue()) for v in vendors],
            )
        except Exception as e:
            st.error(f"Ingest failed: {e}")
            return

    st.session_state.eval_id = result["eval_id"]
    st.session_state.eval_status = "metadata_extracted"
    st.session_state.iteration = 1
    st.session_state.metadata = result["metadata"]
    st.session_state.vendors = result["vendors"]
    st.success(f"Tender ingested. Eval ID: {result['eval_id']}")
    st.rerun()
