"""The render budget: actor count and build time may only go down.

`tools/render_bench.py` builds a synthetic model and reports how long the
geometry took to construct and how many actors VTK would have to draw. This test
checks those two numbers against `tools/render-budget.txt`.

The actor count is exact: it is deterministic (each `add_mesh` is one draw call)
and the roadmap target — 10k nodes and 20k frames at 30 fps — depends on keeping
it small. The time ceiling is wide on purpose, because a CI runner is neither
idle nor the developer's machine; it exists to catch an order-of-magnitude
regression, not to police a few milliseconds.
"""

from __future__ import annotations

from pathlib import Path

from tools import render_bench

BUDGET_FILE = Path(__file__).resolve().parents[2] / "tools" / "render-budget.txt"


def _budget() -> dict[str, tuple[int, float]]:
    """Parse ``model actors build_ms`` lines, ignoring comments and blanks."""
    parsed: dict[str, tuple[int, float]] = {}
    for line in BUDGET_FILE.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        name, actors, build_ms = entry.split()
        parsed[name] = (int(actors), float(build_ms))
    return parsed


def test_every_benchmarked_model_has_a_budget() -> None:
    """Adding a model to the benchmark without a ceiling would silently skip it."""
    budget = _budget()

    assert set(budget) == {label for label, *_rest in render_bench.MODELS}


def test_every_model_stays_within_its_budget() -> None:
    budget = _budget()
    over_budget: list[str] = []

    for result in render_bench.run():
        actors, build_ms = budget[result.name]
        if result.actors > actors:
            over_budget.append(f"{result.name}: {result.actors} actors > {actors}")
        if result.build_ms > build_ms:
            over_budget.append(f"{result.name}: {result.build_ms:.0f} ms > {build_ms:.0f} ms")

    assert not over_budget, "Render budget exceeded:\n" + "\n".join(over_budget)
