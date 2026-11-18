"""Simply supported beam, 6 m span, one load pattern per kind of load.

A 2D beam in the X-Z plane, pinned at the left (Ux, Uz) and on a roller at
the right (Uz), a single elastic element 6 m long. Each load pattern holds a
different kind of member load, so the canvas, the cases and the hand checks
below can be compared pattern by pattern:

=========  ===================================================  ==========  ==========
Pattern    Load                                                 Reactions   M midspan
=========  ===================================================  ==========  ==========
DEAD       uniform w = 10 kN/m over the whole span              30 / 30     45.00 kN·m
LIVE       point P = 50 kN at midspan                           25 / 25     75.00 kN·m
EQUIPMENT  two points of 20 kN at 1.5 m and 4.5 m               20 / 20     30.00 kN·m
PARTITION  partial uniform 8 kN/m from 2 m to 4 m               8 / 8       20.00 kN·m
ROOF       triangular 0 → 15 kN/m from left to right            15 / 30     33.75 kN·m
=========  ===================================================  ==========  ==========

(All loads act downward, -Z. ROOF peaks off midspan: M max = wL²/(9√3) =
34.64 kN·m at x = L/√3 = 3.46 m.) One static case per pattern, plus the
combination 1.2 DEAD + 1.6 (LIVE + EQUIPMENT + PARTITION + ROOF).

Run from the repository root:

    python examples/simply_supported_load_patterns.py

Produces ``examples/simply_supported_load_patterns.osmodel``.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    CombinationTerm,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    LoadCombination,
    Node,
    PlainLoadPattern,
    PointElementLoad,
    Project,
    ProjectMeta,
    StaticCase,
    TrapezoidalElementLoad,
    UniformElementLoad,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project

SPAN = 6.0  # m
KN = 1_000.0  # N

PATTERNS = ("DEAD", "LIVE", "EQUIPMENT", "PARTITION", "ROOF")


def build_simply_supported() -> Project:
    """The 6 m beam with five load patterns, five static cases and one combination."""
    pinned = (True, False, True, False, False, False)  # Ux, Uz
    roller = (False, False, True, False, False, False)  # Uz
    # In the X-Z plane a horizontal member's local y points up (+Z): a
    # downward load is a negative wy / py.
    loads: dict[str, dict[str, list]] = {
        "DEAD": {"element_loads": [UniformElementLoad(element_id=1, wy=-10 * KN)]},
        "LIVE": {"point_loads": [PointElementLoad(element_id=1, py=-50 * KN, x=0.5)]},
        "EQUIPMENT": {
            "point_loads": [
                PointElementLoad(element_id=1, py=-20 * KN, x=1.5 / SPAN),
                PointElementLoad(element_id=1, py=-20 * KN, x=4.5 / SPAN),
            ]
        },
        "PARTITION": {
            "distributed_loads": [
                TrapezoidalElementLoad(
                    element_id=1,
                    x_start=2.0 / SPAN,
                    x_end=4.0 / SPAN,
                    wy_start=-8 * KN,
                    wy_end=-8 * KN,
                )
            ]
        },
        "ROOF": {
            "distributed_loads": [
                TrapezoidalElementLoad(element_id=1, wy_start=0.0, wy_end=-15 * KN)
            ]
        },
    }
    patterns = [
        PlainLoadPattern(id=i, name=name, time_series_id=1, **loads[name])
        for i, name in enumerate(PATTERNS, start=1)
    ]
    cases = [
        StaticCase(id=i, name=name, pattern_ids=[i]) for i, name in enumerate(PATTERNS, start=1)
    ]
    return Project(
        meta=ProjectMeta(name="Simply supported beam, 6 m", units=UnitSystem.SI_M_N),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, name="A", coords=(0.0, 0.0, 0.0), restraint=pinned),
            Node(id=2, name="B", coords=(SPAN, 0.0, 0.0), restraint=roller),
        ],
        sections=[
            # W14x30-like: the deflections are realistic, the forces do not depend on it.
            ElasticSection(id=1, name="W14X30", E=200e9, A=5.7e-3, Iz=1.21e-4),
        ],
        elements=[ElasticBeamColumn(id=1, name="Beam", nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=patterns,
        analyses=cases,
        combinations=[
            LoadCombination(
                id=1,
                name="1.2D+1.6L",
                terms=[
                    CombinationTerm(ref_id=1, factor=1.2),
                    *(CombinationTerm(ref_id=i, factor=1.6) for i in range(2, len(PATTERNS) + 1)),
                ],
            )
        ],
    )


def main() -> None:
    project = build_simply_supported()
    project.validate_references()
    print(
        f"Built '{project.meta.name}': {len(project.load_patterns)} load patterns, "
        f"{len(project.analyses)} cases, {len(project.combinations)} combination."
    )
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
