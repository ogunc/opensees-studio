"""Elastic Frame Example — OpenSees Examples Manual, Example 4.

3-story 3-bay 2D elastic moment-resisting frame under gravity
(distributed beam loads) + a lateral reference pattern (point loads
at each floor's leftmost joint) + a 5-mode eigenvalue analysis.

Matches the Tcl walkthrough at:
https://opensees.berkeley.edu/wiki/index.php?title=Elastic_Frame_Example

Model (kip-in-ksi, ndm=2, ndf=3):

      Floor 3 (z = 486")  13 ──beam19── 14 ──beam20── 15 ──beam21── 16
                           │            │             │             │
                         col9         col10         col11         col12
                           │            │             │             │
      Floor 2 (z = 324")   9 ──beam16── 10 ─beam17── 11 ──beam18── 12
                           │            │             │             │
                         col5          col6          col7          col8
                           │            │             │             │
      Floor 1 (z = 162")   5 ──beam13── 6  ─beam14── 7  ──beam15── 8
                           │            │             │             │
                         col1          col2          col3          col4
                           │            │             │             │
      Base   (z =   0")    1            2             3             4
                         (fixed)     (fixed)       (fixed)       (fixed)
               x =        0         360           720          1080

Sections (AISC W-shapes):
    - Exterior column (lines 1, 4):      W14X257  A=75.6   Iz=3400
    - Interior column (lines 2, 3):      W14X311  A=91.4   Iz=4330
    - Floor-1 beam:                      W33X118  A=34.7   Iz=5900
    - Floor-2 beam:                      W30X116  A=34.2   Iz=4930
    - Floor-3 beam:                      W24X68   A=20.1   Iz=1830
    - E = 29000 ksi for all.

Columns use the PDelta geometric transformation to capture P-Δ; beams
use Linear. Gravity is a Constant time series with a uniform
distributed load per beam (reference tributary intensity Load / 4 /
bay — matches the Tcl ``eleLoad -type -beamUniform [expr -Load/(4*bay)]``).
The lateral pattern uses a Linear time series with single-node point
loads (220 / 180 / 90 kip at floors 1 / 2 / 3 respectively).

Expected results (verified against the Tcl reference):
    - Gravity ΣFy at base:       ≈ 2505 kip  (Σw · Σbeam-length · 3 floors)
    - Gravity+Lateral ΣFx:       ≈ -490 kip
    - First five periods (s):    1.0256, 0.3498, 0.1919, 0.1562, 0.1307

GUI walkthrough: File → Open → elastic_frame.osmodel → Analyze →
Run → "Gravity + Lateral" → Display → Show Force Diagram / Modal.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ConstantTimeSeries,
    CoordinateGridSystem,
    ElasticBeamColumn,
    ElasticSection,
    GridSystem,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    UniformElementLoad,
    UnitSystem,
    make_grid_lines,
)
from opensees_studio.services import load_project, save_project


# Frame geometry (inches).
BAY = 360.0           # 30 ft — bay width
H_STORY = 162.0       # 13.5 ft — story height
N_BAYS = 3
N_STORIES = 3

# Material + section (kip, in, ksi).
E = 29000.0

# Column sections — exterior W14X257 vs interior W14X311.
A_COL_EXT, IZ_COL_EXT = 75.6, 3400.0
A_COL_INT, IZ_COL_INT = 91.4, 4330.0

# Beam sections — per floor.
A_BEAM_F1, IZ_BEAM_F1 = 34.7, 5900.0     # W33X118 (floor 1)
A_BEAM_F2, IZ_BEAM_F2 = 34.2, 4930.0     # W30X116 (floor 2)
A_BEAM_F3, IZ_BEAM_F3 = 20.1, 1830.0     # W24X68  (floor 3)

# Gravity loading (total weight per floor, kip).
LOAD_F1 = 1185.0
LOAD_F2 = 1185.0
LOAD_F3 = 970.0

# Lateral loading (kip, applied at each floor's leftmost joint, +X).
P_F1 = 220.0
P_F2 = 180.0
P_F3 = 90.0

# Gravity constant.
G = 386.4             # in/s²

# ─── ID layout ─────────────────────────────────────────────────────
# Nodes: row-major, starting from (x=0, y=0). 4 columns × 4 rows = 16.
#   row r (0=base, 1=floor-1, 2=floor-2, 3=floor-3), col c (0..3):
#   id = 1 + r*4 + c
#
# Elements:
#   cols 1..12  : columns (bottom-to-top, left-to-right within each story)
#   cols 13..21 : beams   (bottom-to-top, left-to-right within each floor)
#
def _node_id(row: int, col: int) -> int:
    return 1 + row * (N_BAYS + 1) + col


def _col_id(story: int, col: int) -> int:
    # Story 1..3, col 0..3.
    return (story - 1) * (N_BAYS + 1) + col + 1


def _beam_id(floor: int, bay: int) -> int:
    # Floor 1..3, bay 0..(N_BAYS-1).
    n_cols_total = N_STORIES * (N_BAYS + 1)     # 12
    return n_cols_total + (floor - 1) * N_BAYS + bay + 1


def build_elastic_frame() -> Project:
    nodes: list[Node] = []
    m_floor = {
        1: LOAD_F1 / ((N_BAYS + 1) * G),        # mass per node at floor 1
        2: LOAD_F2 / ((N_BAYS + 1) * G),
        3: LOAD_F3 / ((N_BAYS + 1) * G),
    }
    for r in range(N_STORIES + 1):
        for c in range(N_BAYS + 1):
            nid = _node_id(r, c)
            x = c * BAY
            y = r * H_STORY
            if r == 0:
                # Base nodes: fix tx, ty, rz (the only active DOFs in ndm=2 ndf=3).
                restraint = (True, True, False, False, False, True)
                mass = (0.0,) * 6
            else:
                # Floor nodes: all 6 slots free. The runner's dof_idx
                # picks only (tx, ty, rz) = (0, 1, 5) out of this tuple
                # when emitting 2D. A stray True at index 5 would fix Rz
                # at every floor node and make the frame act rigid-joint.
                restraint = (False,) * 6
                m = m_floor[r]
                mass = (m, m, 0.0, 0.0, 0.0, 0.0)
            nodes.append(Node(
                id=nid, name=f"N{nid}",
                coords=(x, y, 0.0),
                restraint=restraint, mass=mass,
            ))

    # Sections: exterior col, interior col, beam-F1, beam-F2, beam-F3.
    sections = [
        ElasticSection(id=1, name="W14X257-ColExt",
                       E=E, A=A_COL_EXT, Iz=IZ_COL_EXT,
                       Iy=IZ_COL_EXT, G=11200.0, J=1.0),
        ElasticSection(id=2, name="W14X311-ColInt",
                       E=E, A=A_COL_INT, Iz=IZ_COL_INT,
                       Iy=IZ_COL_INT, G=11200.0, J=1.0),
        ElasticSection(id=3, name="W33X118-Beam1",
                       E=E, A=A_BEAM_F1, Iz=IZ_BEAM_F1,
                       Iy=IZ_BEAM_F1, G=11200.0, J=1.0),
        ElasticSection(id=4, name="W30X116-Beam2",
                       E=E, A=A_BEAM_F2, Iz=IZ_BEAM_F2,
                       Iy=IZ_BEAM_F2, G=11200.0, J=1.0),
        ElasticSection(id=5, name="W24X68-Beam3",
                       E=E, A=A_BEAM_F3, Iz=IZ_BEAM_F3,
                       Iy=IZ_BEAM_F3, G=11200.0, J=1.0),
    ]

    # Elements — 12 columns (PDelta) + 9 beams (Linear).
    elements: list[ElasticBeamColumn] = []
    for s in range(1, N_STORIES + 1):
        for c in range(N_BAYS + 1):
            sec_id = 1 if c in (0, N_BAYS) else 2     # exterior vs interior
            elements.append(ElasticBeamColumn(
                id=_col_id(s, c), name=f"Col-S{s}-C{c}",
                nodes=(_node_id(s - 1, c), _node_id(s, c)),
                section_id=sec_id, geom_transf="PDelta",
            ))
    beam_sec = {1: 3, 2: 4, 3: 5}
    for f in range(1, N_STORIES + 1):
        for b in range(N_BAYS):
            elements.append(ElasticBeamColumn(
                id=_beam_id(f, b), name=f"Beam-F{f}-B{b}",
                nodes=(_node_id(f, b), _node_id(f, b + 1)),
                section_id=beam_sec[f], geom_transf="Linear",
            ))

    # Gravity distributed load per beam: w = -Load / (4 × bay). The Tcl
    # reference divides by 4 (number of column lines), not by the number
    # of bays — so the distributed load represents a *reference* tributary
    # intensity, not the total floor weight spread over all beams.
    # Corresponding reference values: w1 = w2 = -0.8229 kip/in, w3 = -0.6736.
    floor_total = {1: LOAD_F1, 2: LOAD_F2, 3: LOAD_F3}
    gravity_element_loads = [
        UniformElementLoad(
            element_id=_beam_id(f, b),
            wy=-floor_total[f] / ((N_BAYS + 1) * BAY),
        )
        for f in range(1, N_STORIES + 1)
        for b in range(N_BAYS)
    ]

    # Lateral point loads at each floor's leftmost joint (+X).
    lateral_nodes = {
        _node_id(1, 0): P_F1,
        _node_id(2, 0): P_F2,
        _node_id(3, 0): P_F3,
    }

    return Project(
        meta=ProjectMeta(
            name="Elastic Frame (OpenSees Ex 4)",
            author="OpenSees Examples Manual",
            description=(
                "3-story 3-bay 2D elastic frame, AISC W-shape sections, "
                "gravity (distributed) + lateral (point) + 5-mode eigen."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2, ndf=3,
        coord_systems=[
            CoordinateGridSystem(
                name="Global",
                grid=GridSystem(
                    x_grid_lines=make_grid_lines(
                        "X", [c * BAY for c in range(N_BAYS + 1)],
                    ),
                    y_grid_lines=make_grid_lines(
                        "Y", [r * H_STORY for r in range(N_STORIES + 1)],
                    ),
                    z_grid_lines=make_grid_lines("Z", [0.0]),
                ),
            ),
        ],
        nodes=nodes,
        sections=sections,
        elements=elements,
        time_series=[
            ConstantTimeSeries(id=1, name="Gravity"),
            LinearTimeSeries(id=2, name="Lateral"),
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1, name="Gravity",
                time_series_id=1,
                element_loads=gravity_element_loads,
            ),
            PlainLoadPattern(
                id=2, name="Lateral",
                time_series_id=2,
                nodal_loads=[
                    NodalLoad(node_id=nid, forces=(P, 0, 0, 0, 0, 0))
                    for nid, P in lateral_nodes.items()
                ],
            ),
        ],
        analyses=[
            # Gravity alone — ΣFy at base should equal +3340 kip.
            StaticCase(
                id=1, name="Gravity",
                pattern_ids=[1],
                n_steps=1, load_factor_increment=1.0,
                system="BandGeneral", constraints="Transformation",
                integrator="LoadControl", algorithm="Linear",
                test="NormDispIncr", tolerance=1e-10, max_iter=10,
            ),
            # Gravity + lateral — ΣFx at base should equal -490 kip.
            StaticCase(
                id=2, name="Gravity+Lateral",
                pattern_ids=[1, 2],
                n_steps=1, load_factor_increment=1.0,
                system="BandGeneral", constraints="Transformation",
                integrator="LoadControl", algorithm="Linear",
                test="NormDispIncr", tolerance=1e-10, max_iter=10,
            ),
            # Eigen analysis on the lumped-mass model — 5 modes.
            ModalCase(id=3, name="Modal-5", n_modes=5),
        ],
    )


def main() -> None:
    project = build_elastic_frame()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  ndm={project.ndm}, ndf={project.ndf}, "
          f"units={project.meta.units.value}")
    print(f"  {len(project.nodes)} nodes, {len(project.elements)} elements")
    print(f"  Total gravity load: {LOAD_F1 + LOAD_F2 + LOAD_F3:.0f} kip")
    print(f"  Total lateral load: {P_F1 + P_F2 + P_F3:.0f} kip")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
