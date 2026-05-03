"""Sidebar: role dropdown + actor id + current eval summary + reset."""

from __future__ import annotations

import streamlit as st

from .. import api_client
from ..state import ROLES, reset_eval


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### Role")
        prev_role = st.session_state.role
        role = st.selectbox(
            "Acting as",
            ROLES,
            index=ROLES.index(st.session_state.role),
            label_visibility="collapsed",
            key="role_select",
        )
        st.session_state.role = role
        # Auto-suggest a fresh actor_id when role changes (user can override)
        if role != prev_role:
            st.session_state.actor_id = f"{role.lower()}1"

        st.session_state.actor_id = st.text_input(
            "Your ID", value=st.session_state.actor_id
        )

        st.divider()

        if st.session_state.eval_id:
            st.markdown("### Current Evaluation")
            st.code(st.session_state.eval_id, language=None)
            st.caption(f"Status: `{st.session_state.eval_status or 'unknown'}`")
            st.caption(f"Iteration: {st.session_state.iteration or '-'}")
            if st.button("Reset session", use_container_width=True):
                reset_eval()
                st.rerun()

            st.divider()
            st.markdown("### Audit Log")
            try:
                audit = api_client.audit_log(st.session_state.eval_id)
                for ev in audit["events"]:
                    st.markdown(
                        f'<span class="audit-event-action">{ev["action"]}</span>'
                        f' &middot; {ev["actor_role"]} `{ev["actor_id"]}`'
                        f'<br><small>{ev.get("notes") or ""}</small>',
                        unsafe_allow_html=True,
                    )
            except Exception as e:
                st.caption(f"Audit fetch failed: {e}")
        else:
            st.caption("No evaluation in session.")

        st.divider()
        st.caption("API: `" + api_client._base() + "`")
