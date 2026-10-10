"""The frozen bundle re-enters itself as the analysis CLI.

A bundle has no ``python -m`` to spawn, so the child analysis process is the
bundle's own executable started with ``--run-analysis-cli`` and dispatched
back to :func:`opensees_studio.run.main` by ``__main__``. These tests pin
both halves of that contract without needing a frozen build.
"""

from __future__ import annotations

import sys
import types

import pytest

from opensees_studio.child_cli import CLI_FLAG, analysis_cli_command


def test_a_source_install_spawns_python_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)

    assert analysis_cli_command() == [sys.executable, "-u", "-m", "opensees_studio.run"]


def test_a_frozen_bundle_re_enters_its_own_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    command = analysis_cli_command()

    assert command == [sys.executable, CLI_FLAG]
    # No `-m`: a bundle has no module search path, only itself.
    assert "-m" not in command


def test_the_flag_is_not_an_option_the_cli_would_reject() -> None:
    """It is consumed by ``__main__`` before the CLI parses anything."""
    assert CLI_FLAG.startswith("--")
    assert " " not in CLI_FLAG


# ─────────────────────── __main__ dispatch ───────────────────────
@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the argv the analysis CLI is called with."""
    calls: list[list[str]] = []

    def _main(argv: list[str] | None = None) -> int:
        calls.append(list(argv or []))
        return 0

    monkeypatch.setattr("opensees_studio.run.main", _main)
    return calls


@pytest.fixture
def fake_gui(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture the argv the GUI is launched with, without importing Qt."""
    calls: list[list[str]] = []
    module = types.ModuleType("opensees_studio.app")

    def _run(argv: list[str]) -> int:
        calls.append(list(argv))
        return 0

    module.run = _run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opensees_studio.app", module)
    return calls


def test_the_child_flag_runs_the_cli(
    monkeypatch: pytest.MonkeyPatch, fake_cli: list[list[str]], fake_gui: list[list[str]]
) -> None:
    from opensees_studio.__main__ import main

    monkeypatch.setattr(
        sys, "argv", ["OpenSeesStudio", CLI_FLAG, "--project", "p.osmodel", "--out", "d"]
    )

    assert main() == 0
    assert fake_cli == [["--project", "p.osmodel", "--out", "d"]]
    assert fake_gui == []


def test_no_flag_launches_the_gui(
    monkeypatch: pytest.MonkeyPatch, fake_cli: list[list[str]], fake_gui: list[list[str]]
) -> None:
    from opensees_studio.__main__ import main

    monkeypatch.setattr(sys, "argv", ["OpenSeesStudio"])

    assert main() == 0
    assert fake_gui == [["OpenSeesStudio"]]
    assert fake_cli == []


def test_an_option_that_only_looks_like_the_flag_opens_the_gui(
    monkeypatch: pytest.MonkeyPatch, fake_cli: list[list[str]], fake_gui: list[list[str]]
) -> None:
    """Only argv[1] counts: a path that happens to contain the text is not the flag."""
    from opensees_studio.__main__ import main

    monkeypatch.setattr(sys, "argv", ["OpenSeesStudio", "--project", CLI_FLAG])

    assert main() == 0
    assert fake_cli == []
    assert fake_gui == [["OpenSeesStudio", "--project", CLI_FLAG]]
