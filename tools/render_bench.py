"""Render benchmark: geometry build time and draw calls for synthetic models.

The renderer builds every category from the project on each render, so the cost
that scales with the model is CPU work (PolyData construction, glyphing) plus
the number of actors VTK has to draw. Both are measurable without a GPU: this
drives :class:`ModelRenderer` against a plotter that records the calls instead
of opening an OpenGL context, which is what lets the budget test run in CI.

    python tools/render_bench.py            # table
    python tools/render_bench.py --json     # machine-readable, for the budget test

`tests/tools/test_render_budget.py` reads `tools/render-budget.txt` and fails
when a model needs more actors or more time than recorded there. The budget is a
ratchet: lower it in the commit that improves the numbers.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    UniformElementLoad,
)
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer


class RecordingPlotter:
    """A plotter that counts the actors and labels instead of drawing them."""

    def __init__(self) -> None:
        self.meshes = 0
        self.labels = 0
        #: The datasets handed to add_mesh, so a test can inspect the geometry.
        self.datasets: list[Any] = []
        #: The same, keyed by the actor name the renderer passed (when it did).
        self.named: dict[str, list[Any]] = {}

    def add_mesh(self, mesh: Any = None, *_args: Any, **kwargs: Any) -> object:
        self.meshes += 1
        if mesh is not None:
            self.datasets.append(mesh)
            name = kwargs.get("name")
            if isinstance(name, str):
                self.named.setdefault(name, []).append(mesh)
        return object()

    def add_point_labels(self, *_args: Any, **_kwargs: Any) -> object:
        self.labels += 1
        return object()

    def remove_actor(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def enable_anti_aliasing(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def render(self) -> None:
        return None

    def __getattr__(self, _name: str) -> Any:
        """Any other plotter call is a no-op: this measures the CPU side only."""
        return lambda *_args, **_kwargs: None


@dataclass(frozen=True)
class BenchResult:
    """One measurement: a model size and what it cost to build."""

    name: str
    nodes: int
    frames: int
    build_ms: float
    actors: int
    labels: int


def build_model(
    nx: int,
    ny: int,
    nz: int,
    *,
    restrained: bool = False,
    loads: bool = False,
) -> Project:
    """A full grid of nodes joined along the three axes by elastic frames.

    ``restrained`` fixes the base level, which is what makes the supports path
    matter: one support glyph per node is where the draw calls multiply.
    ``loads`` adds a pattern with a nodal load per node and a uniform load per
    member, which is the densest overlay the renderer draws.
    """
    nodes: list[Node] = []
    index: dict[tuple[int, int, int], int] = {}
    node_id = 1
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                index[(i, j, k)] = node_id
                restraint = (True,) * 6 if restrained and k == 0 else (False,) * 6
                nodes.append(
                    Node(id=node_id, coords=(float(i), float(j), float(k)), restraint=restraint)
                )
                node_id += 1

    elements: list[ElasticBeamColumn] = []
    element_id = 1
    for (i, j, k), start in index.items():
        for step in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            end = index.get((i + step[0], j + step[1], k + step[2]))
            if end is not None:
                elements.append(ElasticBeamColumn(id=element_id, nodes=(start, end), section_id=1))
                element_id += 1

    patterns: list[PlainLoadPattern] = []
    time_series: list[LinearTimeSeries] = []
    if loads:
        patterns = [
            PlainLoadPattern(
                id=1,
                name="Bench",
                time_series_id=1,
                nodal_loads=[
                    NodalLoad(node_id=node.id, forces=(0.0, 0.0, -1000.0, 0.0, 0.0, 0.0))
                    for node in nodes
                ],
                element_loads=[
                    UniformElementLoad(element_id=element.id, wy=-1000.0) for element in elements
                ],
            )
        ]
        time_series = [LinearTimeSeries(id=1)]

    return Project(
        nodes=nodes,
        time_series=time_series,
        load_patterns=patterns,
        sections=[
            ElasticSection(
                id=1,
                name="Bench",
                E=200e9,
                A=0.01,
                Iz=1e-4,
                Iy=1e-4,
                G=80e9,
                J=1e-6,
            )
        ],
        elements=elements,
    )


#: Builds per model; the fastest one is reported. One build alone measured what
#: else the process was doing (a garbage collection of a long test run's objects
#: tripled it), not the renderer.
REPEATS = 3


def measure(project: Project, name: str) -> BenchResult:
    """Build the scene for ``project`` and report the fastest time, actors and labels."""
    build_ms = math.inf
    for _ in range(REPEATS):
        plotter = RecordingPlotter()
        renderer = ModelRenderer(plotter)
        gc.collect()
        started = time.perf_counter()
        renderer.render(project)
        build_ms = min(build_ms, (time.perf_counter() - started) * 1000.0)
    return BenchResult(
        name=name,
        nodes=len(project.nodes),
        frames=len(project.elements),
        build_ms=round(build_ms, 1),
        actors=plotter.meshes,
        labels=plotter.labels,
    )


#: The models the benchmark and the budget test use:
#: (label, nx, ny, nz, restrained, loads).
MODELS: tuple[tuple[str, int, int, int, bool, bool], ...] = (
    ("grid-6x6x3", 6, 6, 3, False, False),
    ("grid-6x6x3-supported", 6, 6, 3, True, False),
    ("grid-6x6x3-loaded", 6, 6, 3, False, True),
    ("grid-10x10x5-supported", 10, 10, 5, True, False),
    # Near the roadmap target and big enough to show per-member work: this is the
    # case where a regression in the per-element paths is visible.
    ("grid-14x14x8-supported", 14, 14, 8, True, False),
)


def run() -> list[BenchResult]:
    """Measure every model in :data:`MODELS`."""
    results: list[BenchResult] = []
    for label, nx, ny, nz, restrained, loads in MODELS:
        project = build_model(nx, ny, nz, restrained=restrained, loads=loads)
        results.append(measure(project, label))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the results as JSON")
    args = parser.parse_args(argv)

    results = run()
    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
        return 0

    print(f"{'model':26} {'nodes':>6} {'frames':>7} {'build ms':>9} {'actors':>7} {'labels':>7}")
    for result in results:
        print(
            f"{result.name:26} {result.nodes:6d} {result.frames:7d} "
            f"{result.build_ms:9.1f} {result.actors:7d} {result.labels:7d}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
