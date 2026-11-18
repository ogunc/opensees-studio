"""Reproducible stability-check benchmarks for frame and truss grids.

    python tools/stability_bench.py --family frame --size 12
    python tools/stability_bench.py --family truss --size 12 --mechanism
    python tools/stability_bench.py --family frame --size 20 --json

The tool reports the equations and ``nnz`` actually captured, the completion
and classification, the method/backend, the wall time and the estimated CSR
memory. It never writes a SAP2000 file or changes a project.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    Node,
    Project,
    TrussElement,
)
from opensees_studio.services.stability import check_stability

FAMILIES = ("frame", "truss")


def _frame(size: int, *, mechanism: bool) -> Project:
    nodes: list[Node] = []
    index: dict[tuple[int, int], int] = {}
    nid = 1
    for j in range(size):
        for i in range(size):
            index[(i, j)] = nid
            # Remove a base restraint in the mechanism variant.
            fixed = j == 0 and not (mechanism and i == size - 1)
            nodes.append(
                Node(
                    id=nid,
                    coords=(i * 3.0, 0.0, j * 3.0),
                    restraint=(True,) * 6 if fixed else (False,) * 6,
                )
            )
            nid += 1
    elements = []
    eid = 1
    for i in range(size):
        for j in range(size):
            if i + 1 < size:
                elements.append(
                    ElasticBeamColumn(
                        id=eid, nodes=(index[(i, j)], index[(i + 1, j)]), section_id=1
                    )
                )
                eid += 1
            if j + 1 < size:
                elements.append(
                    ElasticBeamColumn(
                        id=eid, nodes=(index[(i, j)], index[(i, j + 1)]), section_id=1
                    )
                )
                eid += 1
    return Project(
        ndm=2,
        ndf=3,
        nodes=nodes,
        sections=[ElasticSection(id=1, E=200e9, A=0.01, Iz=1e-4)],
        elements=elements,
    )


def _truss(size: int, *, mechanism: bool) -> Project:
    nodes: list[Node] = []
    index: dict[tuple[int, int], int] = {}
    nid = 1
    for j in range(size):
        for i in range(size):
            index[(i, j)] = nid
            fixed = j == 0
            restraint = (
                (True, False, True, False, False, False)
                if fixed and i == 0
                else ((False, False, True, False, False, False) if fixed else (False,) * 6)
            )
            nodes.append(Node(id=nid, coords=(i * 3.0, 0.0, j * 3.0), restraint=restraint))
            nid += 1
    elements = []
    eid = 1
    for i in range(size):
        for j in range(size):
            for di, dj in ((1, 0), (0, 1)):
                other = index.get((i + di, j + dj))
                if other is not None:
                    elements.append(
                        TrussElement(
                            id=eid,
                            nodes=(index[(i, j)], other),
                            area=0.01,
                            material_id=1,
                        )
                    )
                    eid += 1
            if not mechanism and i + 1 < size and j + 1 < size:
                elements.append(
                    TrussElement(
                        id=eid,
                        nodes=(index[(i, j)], index[(i + 1, j + 1)]),
                        area=0.01,
                        material_id=1,
                    )
                )
                eid += 1
    return Project(
        ndm=2,
        ndf=2,
        nodes=nodes,
        materials=[ElasticUniaxial(id=1, E=200e9)],
        elements=elements,
    )


def run_case(
    family: str, size: int, *, mechanism: bool = False, timeout_s: float | None = None
) -> dict[str, Any]:
    """Build one family and run the stability check; return a JSON-friendly report."""
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}")
    builder = _frame if family == "frame" else _truss
    project = builder(size, mechanism=mechanism)
    started = time.perf_counter()
    report = check_stability(project, timeout_s=timeout_s)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "family": family,
        "size": size,
        "mechanism_variant": mechanism,
        "nodes": len(project.nodes),
        "elements": len(project.elements),
        "elapsed_ms": round(elapsed_ms, 1),
        "n_equations": report.n_equations,
        "nnz": report.nnz,
        "completion": report.completion,
        "classification": report.classification,
        "stable": report.stable,
        "n_mechanisms": report.n_mechanisms,
        "count_kind": report.count_kind,
        "method": report.method,
        "backend": report.backend,
        "memory": report.memory,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--family", choices=FAMILIES, default="frame")
    parser.add_argument("--size", type=int, default=8, help="grid points per side")
    parser.add_argument("--mechanism", action="store_true", help="run the unstable variant")
    parser.add_argument("--timeout", type=float, default=None, help="soft time limit (seconds)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    row = run_case(
        args.family,
        args.size,
        mechanism=args.mechanism,
        timeout_s=args.timeout,
    )
    if args.json:
        print(json.dumps(row, indent=2))
    else:
        print(
            f"{row['family']:5} size={row['size']:3d} nodes={row['nodes']:6d} "
            f"elements={row['elements']:6d} eq={row['n_equations']:6d} nnz={row['nnz']:8d} "
            f"{row['completion']}/{row['classification']} stable={row['stable']} "
            f"{row['elapsed_ms']:.1f} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
