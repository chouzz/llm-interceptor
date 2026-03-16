"""
Developer bootstrap helpers for local clones.

Git does not clone hook scripts from `.git/hooks`, so contributors must install
the project's pre-commit hook once per clone.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(*args: str) -> None:
    """Run a subprocess and surface errors directly to the caller."""
    subprocess.run(args, check=True)


def main() -> None:
    """Install the repository's pre-commit hook for the current clone."""
    repo_root = Path(__file__).resolve().parents[2]

    try:
        _run("git", "-C", str(repo_root), "rev-parse", "--show-toplevel")
    except subprocess.CalledProcessError as exc:
        raise SystemExit("This command must be run from a git checkout.") from exc

    try:
        _run(
            sys.executable,
            "-m",
            "pre_commit",
            "install",
            "--install-hooks",
            "--overwrite",
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            "Failed to install pre-commit hooks. Install dev dependencies first "
            "with 'uv sync --dev' or 'pip install -e .[dev]'."
        ) from exc

    print("pre-commit hooks installed for this clone.")
    print("Run 'pre-commit run --all-files' once if you want to validate the full tree.")


if __name__ == "__main__":
    main()
