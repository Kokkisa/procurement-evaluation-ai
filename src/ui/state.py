"""Streamlit ``session_state`` initialisation + reset helpers."""

from __future__ import annotations

import streamlit as st

# Roles available in the role-switcher dropdown.
ROLES = ("Preparer", "Reviewer", "Approver")

# Keys we manage on session_state. Defining them in one place makes it easy
# to reset the eval-specific portion without nuking the user's role choice.
_EVAL_KEYS = (
    "eval_id",
    "eval_status",
    "iteration",
    "metadata",
    "vendors",
    "technical",
    "commercial",
    "approve_pdf_path",
    "archive_id",
)


def init_session_state() -> None:
    """Set defaults. Streamlit re-runs the script on every interaction so we
    use ``setdefault`` rather than overwriting."""
    st.session_state.setdefault("role", "Preparer")
    st.session_state.setdefault("actor_id", "preparer1")
    for key in _EVAL_KEYS:
        st.session_state.setdefault(key, None)


def reset_eval() -> None:
    """Clear evaluation-specific state but keep role + actor_id."""
    for key in _EVAL_KEYS:
        st.session_state[key] = None
