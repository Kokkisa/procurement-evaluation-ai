"""Streamlit entry point.

Run with:
    streamlit run src/ui/streamlit_app.py --server.port 8501

Routing is *state-driven*: the visible main-panel screen is a pure function
of (role, eval_id, eval_status). The sidebar is always present and lets the
user switch role mid-flow (the demo's stand-in for SSO + RBAC).
"""

from __future__ import annotations

import streamlit as st

from . import styles
from .components.role_switcher import render_sidebar
from .screens import approve, confirmation, final, matrix, review, upload
from .state import init_session_state


def main() -> None:
    st.set_page_config(
        page_title="Procurement Evaluation AI",
        page_icon=":briefcase:",
        layout="wide",
    )
    init_session_state()
    styles.inject()
    render_sidebar()
    _route()


def _route() -> None:
    role = st.session_state.role
    eval_id = st.session_state.eval_id
    status = st.session_state.eval_status

    # No evaluation in session: only the Preparer can start one.
    if eval_id is None:
        upload.render()
        return

    # Eval exists. Pick the screen by current status + role.
    if status == "metadata_extracted":
        if role == "Preparer":
            confirmation.render()
        else:
            _waiting_for("Preparer", "to confirm metadata")
        return

    if status == "eval_ready":
        if role == "Reviewer":
            review.render()
        else:
            matrix.render()
        return

    if status == "review_accepted":
        if role == "Approver":
            approve.render()
        else:
            matrix.render()
            st.info("Reviewer has accepted. Waiting for Approver sign-off.")
        return

    if status in ("approved", "complete_and_pushed"):
        final.render()
        return

    st.error(f"Unhandled evaluation status: {status!r}")


def _waiting_for(role_name: str, action: str) -> None:
    matrix._render_header()
    st.info(f"Waiting for **{role_name}** {action}. Switch role in the sidebar.")


if __name__ == "__main__":
    main()
