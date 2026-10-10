"""Turn a release tag into the notes that belong on its release page.

The publish job of the desktop workflow runs this: a release cut by CI carried
whatever body the release action defaulted to, which was nothing — 0.0.4
shipped with an empty page while its notes sat in `CHANGELOG.md`. Taking them
from the changelog keeps the two in step, and a tag whose section is missing
fails the step instead of publishing a blank release.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"


def release_notes(tag: str, *, changelog: Path = CHANGELOG) -> str:
    """Return the changelog section for ``tag`` (with or without its leading "v").

    Raises:
        LookupError: if the changelog has no section for that version, or the
            section is empty.
    """
    version = tag.removeprefix("v")
    text = changelog.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        re.S | re.M,
    )
    match = pattern.search(text)
    if match is None or not match.group(1).strip():
        raise LookupError(f"CHANGELOG.md has no notes for {version}")
    return match.group(1).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: release_notes.py <tag>", file=sys.stderr)
        return 2
    try:
        sys.stdout.write(release_notes(args[0]))
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
