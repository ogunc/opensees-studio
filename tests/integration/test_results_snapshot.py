"""Every example's results match their pinned snapshot.

``tools/results_snapshot.py`` runs each project in ``examples/`` through the
analysis CLI and reduces each case to a fingerprint (see its docstring). A
quantity that moved by more than ``RTOL`` fails here, with the before and after:
pin an intended change with ``--write --reason`` (which records it in
``docs/results-changes.md``) and announce it under *Results changed* in the
CHANGELOG.
"""

from __future__ import annotations

import pytest

pytest.importorskip("openseespy")

from tools import results_snapshot as snap

pytestmark = pytest.mark.slow

PINNED = snap.load_pinned()


@pytest.fixture(scope="module")
def current() -> dict[str, dict[str, snap.Fingerprint]]:
    return snap.run_all()


def test_every_example_is_pinned(current: dict[str, dict[str, snap.Fingerprint]]) -> None:
    assert sorted(current) == sorted(PINNED), "pin new examples with --write"


@pytest.mark.parametrize("example", sorted(PINNED))
def test_results_match_the_snapshot(
    example: str, current: dict[str, dict[str, snap.Fingerprint]]
) -> None:
    changes = snap.compare({example: PINNED[example]}, {example: current.get(example, {})})
    assert not changes, "results changed:\n" + snap._report(changes)


def test_no_case_errors(current: dict[str, dict[str, snap.Fingerprint]]) -> None:
    failed = [
        f"{example} case {case}: {fp['message']}"
        for example, cases in current.items()
        for case, fp in cases.items()
        if fp.get("kind") == "error"
    ]
    assert not failed, failed
