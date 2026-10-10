"""Run mypy and fail only when it reports more errors than the recorded budget.

`[tool.mypy] strict = true`, and the codebase has a backlog. Running mypy with
no gate at all means new errors land unnoticed; making it blocking today means
fixing several hundred first. A budget is the middle: the number in
`tools/mypy-budget.txt` may only go down.

    python tools/typecheck.py

Lower the budget in the same commit that removes errors. If mypy, typeshed or a
dependency upgrade moves the count, update the budget in that commit too and say
so in the message — do not raise it to paper over new code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET_FILE = ROOT / "tools" / "mypy-budget.txt"
TARGET = "src/opensees_studio"
SHOWN_ON_FAILURE = 30


def budget() -> int:
    """The recorded number of tolerated errors (the file may carry comments)."""
    text = BUDGET_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            return int(stripped)
    raise SystemExit(f"{BUDGET_FILE} has no number in it")


def main() -> int:
    allowed = budget()
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", TARGET],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    errors = [line for line in output.splitlines() if ": error:" in line]
    count = len(errors)
    print(f"mypy: {count} error(s), budget {allowed}")

    if count > allowed:
        print(f"\n{count - allowed} more than the budget. First few:")
        for line in errors[:SHOWN_ON_FAILURE]:
            print(f"  {line}")
        if count > SHOWN_ON_FAILURE:
            print(f"  ... and {count - SHOWN_ON_FAILURE} more")
        print(f"\nFix them, or run `{sys.executable} -m mypy {TARGET}` for the full list.")
        return 1

    if count < allowed:
        print(f"{allowed - count} fewer than the budget: lower {BUDGET_FILE.name} to {count}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
