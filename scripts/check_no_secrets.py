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

# Anthropic admin and standard keys all begin with `sk-ant-`. Tail length
# varies by key type; >=8 trailing chars catches everything in practice.
SECRET_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")


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

    hits: list[str] = []
    for f in files:
        if SECRET_PATTERN.search(_staged_content(f)):
            hits.append(f)

    if hits:
        print("ERROR: Anthropic 'sk-ant-' secret detected in staged files:", file=sys.stderr)
        for h in hits:
            print(f"  - {h}", file=sys.stderr)
        print("Refusing to commit. Remove the secret and re-stage.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
