"""Run the same quality gates locally and in CI; stop on the first failure."""

import os
import subprocess
import sys


def main() -> None:
    python = sys.executable
    npm = "npm.cmd" if os.name == "nt" else "npm"
    commands = [
        [python, "-m", "ruff", "check", "."],
        [python, "-m", "ruff", "format", "--check", "."],
        [python, "-m", "mypy"],
        [python, "-m", "pytest"],
        [npm, "run", "lint"],
        [npm, "run", "typecheck"],
        [npm, "test"],
        [npm, "run", "build"],
        [npm, "run", "format:check"],
    ]
    for command in commands:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
