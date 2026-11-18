"""End-to-end benchmark for large synthetic models.

``render_bench`` measures the renderer alone. This tool measures the stages a
large model actually goes through: build the project, build the scene, save and
load it, and (optionally) solve a static case. Use it before and after an
optimisation, and with ``--profile`` to see the per-stage spans collected by the
in-application monitor.

    python tools/perf_bench.py --size small
    python tools/perf_bench.py --size large --profile --json
    python tools/perf_bench.py --size xlarge --cprofile

The ``--cprofile`` option prints the 30 functions with the largest cumulative
time to stderr, so ``--json`` stays machine-readable.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from opensees_studio.core import StaticCase
from opensees_studio.diagnostics.performance import perf
from opensees_studio.services import load_project, save_project
from opensees_studio.services.opensees_runner import OpenSeesRunner

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import render_bench

#: (nx, ny, nz) for each named size. ``large`` is the render-budget model;
#: ``xlarge`` is the first size where the UI paths start to dominate.
SIZES: dict[str, tuple[int, int, int]] = {
    "tiny": (4, 4, 2),
    "small": (6, 6, 3),
    "medium": (10, 10, 5),
    "large": (14, 14, 8),
    "xlarge": (20, 20, 10),
}


def run_bench(
    *,
    size: str = "small",
    dimensions: tuple[int, int, int] | None = None,
    solver: bool = False,
) -> dict[str, Any]:
    """Run the benchmark once and return a JSON-friendly report."""
    nx, ny, nz = dimensions or SIZES[size]
    label = f"grid-{nx}x{ny}x{nz}"
    report: dict[str, Any] = {
        "size": size if dimensions is None else "custom",
        "dimensions": [nx, ny, nz],
        "solver": solver,
    }

    with perf.span("bench.build_model"):
        project = render_bench.build_model(nx, ny, nz, restrained=True, loads=True)
    report["nodes"] = len(project.nodes)
    report["frames"] = len(project.elements)
    report["load_patterns"] = len(project.load_patterns)

    with perf.span("bench.render"):
        render = render_bench.measure(project, label)
    report["render"] = asdict(render)

    with tempfile.TemporaryDirectory(prefix="osstudio_perf_") as directory:
        path = Path(directory) / "bench.osmodel"
        started = time.perf_counter()
        with perf.span("bench.save"):
            save_project(project, path)
        report["save_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        started = time.perf_counter()
        with perf.span("bench.load"):
            loaded = load_project(path)
        report["load_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        report["save_load_nodes"] = len(loaded.nodes)

    if solver:
        case = StaticCase(id=1, name="Bench", pattern_ids=[1])
        project.analyses = [case]
        project.validate_references()
        started = time.perf_counter()
        try:
            with perf.span("bench.solver"):
                results = OpenSeesRunner(project).run(case)
            report["solver_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
            report["solver_result"] = type(results).__name__
        except Exception as exc:  # the tool must report, not hide, a broken solver
            report["solver_error"] = f"{type(exc).__name__}: {exc}"

    report["perf"] = perf.snapshot() if perf.enabled else None
    return report


def _print_report(report: dict[str, Any]) -> None:
    render = report["render"]
    print(
        f"{report['size']:>7} {report['nodes']:6d} nodes "
        f"{report['frames']:7d} frames {render['build_ms']:8.1f} ms render "
        f"{render['actors']:4d} actors {render['labels']:3d} labels"
    )
    for key in ("save_ms", "load_ms", "solver_ms"):
        if key in report:
            print(f"        {key:12} {report[key]:10.1f} ms")
    if "solver_error" in report:
        print(f"        solver error: {report['solver_error']}")
    if report.get("perf"):
        metrics = report["perf"]["metrics"]
        rows = sorted(metrics.items(), key=lambda item: item[1]["total_ms"], reverse=True)
        print("\n        stage                          last ms   total ms    n")
        for name, values in rows[:20]:
            print(
                f"        {name:30} {values['last_ms']:8.2f} {values['total_ms']:10.2f}"
                f" {values['count']:4d}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", choices=sorted(SIZES), default="small")
    parser.add_argument("--nx", type=int, help="override the model's X count")
    parser.add_argument("--ny", type=int, help="override the model's Y count")
    parser.add_argument("--nz", type=int, help="override the model's Z count")
    parser.add_argument("--solver", action="store_true", help="run a static case")
    parser.add_argument("--profile", action="store_true", help="collect perf spans")
    parser.add_argument("--cprofile", action="store_true", help="profile the whole run")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    if args.profile:
        perf.enable()
    dimensions = None
    if args.nx or args.ny or args.nz:
        base = SIZES[args.size]
        dimensions = (args.nx or base[0], args.ny or base[1], args.nz or base[2])

    profiler: cProfile.Profile | None = None
    if args.cprofile:
        profiler = cProfile.Profile()
        profiler.enable()
    started = time.perf_counter()
    report = run_bench(size=args.size, dimensions=dimensions, solver=args.solver)
    report["wall_ms"] = round((time.perf_counter() - started) * 1000.0, 1)

    if profiler is not None:
        profiler.disable()
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(30)
        print(stream.getvalue(), file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
