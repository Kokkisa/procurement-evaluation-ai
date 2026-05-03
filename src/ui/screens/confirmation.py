"""Confirmation screen — 2 tabs (tender meta + vendor list), Confirm button.

This is the cascading-error gate from spec ADR-0003: a quick human check
on what the metadata agent extracted before the (much more expensive)
evaluation chain runs.
"""

from __future__ import annotations

import streamlit as st

from .. import api_client


def render() -> None:
    st.title("Confirm Tender Metadata + Vendor List")
    st.caption(
        "Review what the metadata agent extracted. Edits made here are local — "
        "the demo doesn't persist tender-metadata edits, but this is where the "
        "preparer would catch a misread before launching the per-vendor eval."
    )

    metadata = dict(st.session_state.metadata or {})
    vendors = list(st.session_state.vendors or [])

    tab_meta, tab_vendors = st.tabs(["Tender Metadata", f"Vendors ({len(vendors)})"])

    with tab_meta:
        c1, c2 = st.columns(2)
        with c1:
            metadata["tender_number"] = st.text_input(
                "Tender Number", value=metadata.get("tender_number", "")
            )
            metadata["tender_floated_date"] = st.text_input(
                "Floated Date", value=metadata.get("tender_floated_date") or ""
            )
            metadata["issuing_organization"] = st.text_input(
                "Issuing Organization",
                value=metadata.get("issuing_organization", ""),
            )
        with c2:
            metadata["tender_name"] = st.text_input(
                "Tender Name", value=metadata.get("tender_name", "")
            )
            metadata["tender_due_date"] = st.text_input(
                "Due Date", value=metadata.get("tender_due_date") or ""
            )
            metadata["location"] = st.text_input(
                "Location", value=metadata.get("location") or ""
            )

    with tab_vendors:
        if not vendors:
            st.warning("No vendors detected.")
        else:
            for i, v in enumerate(vendors):
                cols = st.columns([4, 1, 1])
                with cols[0]:
                    new_name = st.text_input(
                        f"Vendor {i + 1}", value=v["vendor_name"], key=f"vname_{i}"
                    )
                    vendors[i] = {**v, "vendor_name": new_name}
                with cols[1]:
                    st.metric("Docs", v["document_count"])
                with cols[2]:
                    st.metric("MSME", "Yes" if v.get("detected_msme") else "No")

    st.divider()

    cols = st.columns([3, 1])
    with cols[1]:
        confirm = st.button("Confirm and Run Evaluation", type="primary", use_container_width=True)

    if not confirm:
        return

    with st.spinner(
        "Running CriteriaExtractionAgent + VendorEvaluationAgent... "
        "(this can take a minute or two — multiple LLM calls in parallel)"
    ):
        try:
            result = api_client.confirm(
                eval_id=st.session_state.eval_id,
                actor_id=st.session_state.actor_id,
            )
        except Exception as e:
            st.error(f"Confirm failed: {e}")
            return

    st.session_state.eval_status = "eval_ready"
    st.session_state.iteration = result["iteration"]
    st.session_state.technical = result["technical"]
    st.session_state.commercial = result["commercial"]
    st.success("Evaluation complete. Switch role to Reviewer to take action.")
    st.rerun()
