"""CSS injected at app startup to give the matrix table a credible PSU
evaluation look — bordered cells, dark header band, fixed-width numerics,
verdict-coded background tints."""

from __future__ import annotations

import streamlit as st

CSS = """
<style>
    .proceval-matrix {
        border-collapse: collapse;
        width: 100%;
        font-family: 'Consolas', 'Courier New', monospace;
        font-size: 12px;
    }
    .proceval-matrix th, .proceval-matrix td {
        border: 1px solid #444;
        padding: 6px 8px;
        vertical-align: top;
        word-break: break-word;
    }
    .proceval-matrix thead th {
        background: #1f3349;
        color: #ffffff;
        font-weight: bold;
        text-align: left;
    }
    .proceval-matrix th.vendor {
        text-align: center;
        font-size: 11px;
    }
    .proceval-matrix th.vendor .msme-badge {
        display: inline-block;
        background: #5e35b1;
        color: white;
        font-size: 9px;
        padding: 1px 4px;
        margin-left: 4px;
        border-radius: 2px;
    }
    .proceval-matrix td.cell-pass     { background: #d4edda; }
    .proceval-matrix td.cell-fail     { background: #f8d7da; }
    .proceval-matrix td.cell-partial  { background: #fff3cd; }
    .proceval-matrix td.cell-na       { background: #e9ecef; color: #555; }
    .proceval-matrix td .verdict-tag {
        display: inline-block;
        font-weight: bold;
        font-size: 10px;
        padding: 1px 4px;
        margin-bottom: 2px;
    }
    .proceval-matrix td .verdict-tag.pass    { color: #155724; }
    .proceval-matrix td .verdict-tag.fail    { color: #721c24; }
    .proceval-matrix td .verdict-tag.partial { color: #856404; }
    .proceval-matrix tr.overall-row td {
        background: #1f3349;
        color: #ffffff;
        font-weight: bold;
    }
    .proceval-matrix tr.overall-row td.cell-pass { background: #1e7e34; }
    .proceval-matrix tr.overall-row td.cell-fail { background: #b21f2d; }
    .proceval-matrix td.col-sno         { width: 38px; text-align: center; }
    .proceval-matrix td.col-criterion   { width: 200px; }
    .proceval-matrix td.col-requirement { width: 220px; }
    .audit-event-action {
        font-family: 'Consolas', 'Courier New', monospace;
        font-weight: bold;
    }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
