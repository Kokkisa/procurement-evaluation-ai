"""Refuse the commit if any staged file contains an Anthropic API key.

Belt-and-suspenders defense alongside .gitignore. Runs as a pre-commit hook
or as `make check-secrets`.

Wire as a hook with:
    make install-hooks

Exit codes:
    0  — clean (no secrets in staged files)
    1  — secret detected (file list printed to stderr)
    2  — git invocation failed (likely run outside a repo)
"""

from __future__ import annotations

import re
import subprocess
import sys

# Patterns we refuse to commit. Each is anchored on the well-known prefix so
# random base64 noise doesn't false-positive.
#   sk-ant-      Anthropic API keys (standard + admin)
#   lsv2_pt_     LangSmith personal-access tokens
#   lsv2_sk_     LangSmith service-account keys
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"lsv2_pt_[A-Za-z0-9_-]{8,}"),
    re.compile(r"lsv2_sk_[A-Za-z0-9_-]{8,}"),
]


def _matched_pattern(content: str) -> str | None:
    """Return a sanitized prefix label (never the secret value itself)."""
    for pat in SECRET_PATTERNS:
        m = pat.search(content)
        if m:
            full = m.group(0)
            for prefix in ("sk-ant-", "lsv2_pt_", "lsv2_sk_"):
                if full.startswith(prefix):
                    return prefix + "*"
            return "***"
    return None


def _staged_files() -> list[str]:
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(res.stderr, file=sys.stderr)
        sys.exit(2)
    return [f for f in res.stdout.splitlines() if f.strip()]


def _staged_content(path: str) -> str:
    res = subprocess.run(
        ["git", "show", f":{path}"],
        capture_output=True,
    )
    if res.returncode != 0:
        return ""
    try:
        return res.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def main() -> int:
    files = _staged_files()
    if not files:
        return 0

    hits: list[tuple[str, str]] = []
    for f in files:
        prefix = _matched_pattern(_staged_content(f))
        if prefix:
            hits.append((f, prefix))

    if hits:
        print("ERROR: secret-like token detected in staged files:", file=sys.stderr)
        for path, prefix in hits:
            print(f"  - {path}  (pattern {prefix})", file=sys.stderr)
        print("Refusing to commit. Remove the secret and re-stage.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
