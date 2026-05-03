"""Inline audit-log renderer (used in the final-state screen)."""

from __future__ import annotations

import html

import streamlit as st

from .. import api_client


def render_inline(eval_id: str) -> None:
    """Render the full audit log as a chronological table for the post-push view."""
    try:
        log = api_client.audit_log(eval_id)
    except Exception as e:
        st.error(f"Failed to fetch audit log: {e}")
        return

    rows = []
    rows.append(
        '<table class="proceval-matrix"><thead><tr>'
        "<th>#</th><th>Action</th><th>Role</th><th>Actor</th><th>Notes</th><th>When</th>"
        "</tr></thead><tbody>"
    )
    for ev in log["events"]:
        notes = (ev.get("notes") or "")[:300]
        rows.append(
            "<tr>"
            f"<td class='col-sno'>{ev['id']}</td>"
            f"<td><b>{html.escape(ev['action'])}</b></td>"
            f"<td>{html.escape(ev['actor_role'])}</td>"
            f"<td>{html.escape(ev['actor_id'])}</td>"
            f"<td><small>{html.escape(notes)}</small></td>"
            f"<td><small>{html.escape(ev['occurred_at'][:19] if ev.get('occurred_at') else '')}</small></td>"
            "</tr>"
        )
    rows.append("</tbody></table>")
    st.markdown("".join(rows), unsafe_allow_html=True)
