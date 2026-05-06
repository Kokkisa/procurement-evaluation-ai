"""Thin httpx wrappers around the FastAPI endpoints.

The UI talks to the API over HTTP — never touches the DB directly. That
means the Streamlit layer can be swapped for a React frontend later
without touching any business logic. Set ``PROCEVAL_API_URL`` to point
the UI at a non-default API host.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0
LONG_TIMEOUT = 600.0  # /confirm + /review/reject re-eval can take minutes


def _base() -> str:
    return os.environ.get("PROCEVAL_API_URL", "http://localhost:8000").rstrip("/")


def health() -> dict[str, Any]:
    r = httpx.get(f"{_base()}/health", timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    return r.json()


def ingest(
    actor_id: str,
    tender: tuple[str, bytes],
    vendor_files: list[tuple[str, bytes]],
) -> dict[str, Any]:
    """``tender`` is (filename, bytes). ``vendor_files`` is list[(filename, bytes)]."""
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("tender", (tender[0], tender[1], "application/pdf"))
    ]
    for name, payload in vendor_files:
        ctype = "application/zip" if name.lower().endswith(".zip") else "application/pdf"
        files.append(("vendor_files", (name, payload, ctype)))
    r = httpx.post(
        f"{_base()}/ingest",
        data={"actor_id": actor_id},
        files=files,
        timeout=LONG_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def confirm(eval_id: str, actor_id: str) -> dict[str, Any]:
    r = httpx.post(
        f"{_base()}/confirm/{eval_id}",
        json={"actor_id": actor_id},
        timeout=LONG_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def review_accept(eval_id: str, actor_id: str) -> dict[str, Any]:
    r = httpx.post(
        f"{_base()}/review/{eval_id}/accept",
        json={"actor_id": actor_id},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def review_reject(eval_id: str, actor_id: str, feedback_text: str) -> dict[str, Any]:
    r = httpx.post(
        f"{_base()}/review/{eval_id}/reject",
        json={"actor_id": actor_id, "feedback_text": feedback_text},
        timeout=LONG_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def approve(eval_id: str, actor_id: str) -> dict[str, Any]:
    r = httpx.post(
        f"{_base()}/approve/{eval_id}",
        json={"actor_id": actor_id},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def push(eval_id: str, actor_id: str) -> dict[str, Any]:
    r = httpx.post(
        f"{_base()}/push/{eval_id}",
        json={"actor_id": actor_id},
        timeout=DEFAULT_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def audit_log(eval_id: str) -> dict[str, Any]:
    r = httpx.get(f"{_base()}/audit/{eval_id}", timeout=DEFAULT_TIMEOUT)
    r.raise_for_status()
    return r.json()
