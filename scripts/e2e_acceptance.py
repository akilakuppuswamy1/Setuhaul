"""Run live E2E acceptance scripts with a fixture reset before each scenario."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, args: list[str]) -> None:
    print(f"\n>>> {label}")
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    python = sys.executable
    scenarios = [
        ("stale proposal", "scripts/e2e_stale_proposal.py"),
        ("concurrency race", "scripts/e2e_concurrency_race.py"),
        ("hero flow", "scripts/e2e_hero_flow.py"),
    ]
    for label, script in scenarios:
        run("seed fixtures", [python, "scripts/seed_e2e_fixtures.py"])
        run(label, [python, script])
    print("\nE2E ACCEPTANCE PASS")


if __name__ == "__main__":
    main()
