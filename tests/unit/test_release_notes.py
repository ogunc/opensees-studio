"""The release notes come from the changelog, or the release fails.

0.0.4 was published with an empty release page while its notes were in
``CHANGELOG.md``; the publish job now extracts them, and a missing or empty
section has to be an error rather than a blank page.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.release_notes import main, release_notes

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def test_the_notes_are_the_section_of_the_released_version() -> None:
    notes = release_notes("v0.0.4")
    assert notes.startswith("The AISC v16 shape library")
    assert "### Fixed" in notes
    assert "force diagram" in notes


def test_the_notes_stop_at_the_next_version() -> None:
    notes = release_notes("v0.0.4")
    assert "## [0.0.3]" not in notes
    assert "The first release built entirely by CI" not in notes


def test_the_leading_v_is_optional() -> None:
    assert release_notes("0.0.4") == release_notes("v0.0.4")


def test_a_version_without_a_section_is_an_error() -> None:
    with pytest.raises(LookupError, match=r"no notes for 9\.9\.9"):
        release_notes("v9.9.9")


def test_an_empty_section_is_an_error(tmp_path: Path) -> None:
    """`Unreleased` is empty by design; cutting a release from it must not pass."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "## [Unreleased]\n\n## [1.2.3] — 2026-01-01\n\n## [1.2.2] — 2025-12-31\n\n- old\n",
        encoding="utf-8",
    )
    with pytest.raises(LookupError, match=r"no notes for 1\.2\.3"):
        release_notes("v1.2.3", changelog=changelog)
    assert release_notes("v1.2.2", changelog=changelog) == "- old\n"


def test_main_writes_the_notes_and_reports_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["v0.0.4"]) == 0
    assert capsys.readouterr().out.startswith("The AISC v16 shape library")

    assert main([]) == 2
    assert "usage" in capsys.readouterr().err

    assert main(["v9.9.9"]) == 1
    assert "no notes for 9.9.9" in capsys.readouterr().err
