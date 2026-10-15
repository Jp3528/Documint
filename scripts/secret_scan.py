"""Scan committed history with the pinned official Gitleaks image, redacting all findings."""

import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{root}:/repo:ro",
            "ghcr.io/gitleaks/gitleaks:v8.30.1",
            "git",
            "/repo",
            "--redact",
            "--no-banner",
            "--log-opts=--all",
        ],
        check=True,
        cwd=root,
    )


if __name__ == "__main__":
    main()
