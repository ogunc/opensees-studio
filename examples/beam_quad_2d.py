"""Simply Supported Beam with 2D Solid (Quad) Elements — OpenSees Ex 6.4.

A 40" × 10" simply supported deep beam meshed with 16×4 plane-stress
quadrilateral elements under two centre-span vertical loads (one at the
top midspan, one at the bottom midspan, each 1 kip downward). The
load is ramped up over 10 LoadControl steps, giving a final midspan
deflection of ~0.394 in. A second case then *removes* the preload and
lets the beam free-vibrate with 2% stiffness-proportional damping for
1500 Newmark steps at dt = 0.5 s — reproducing the full Tcl flow.

Matches the Tcl walkthrough at:
https://opensees.berkeley.edu/wiki/index.php?title=Simply_supported_beam_modeled_with_two_dimensional_solid_elements

Model (kip, in, sec):
    - Geometry:  L = 40 in, H = 10 in, t = 1 in (plane stress)
    - Material:  ElasticIsotropic — E = 1000 ksi, ν = 0.25, ρ = 3.0
    - Elements:  16 × 4 = 64 four-node quads (``quad`` variant,
                 ``PlaneStress2D`` formulation)
    - Supports:  pin at node 1 (bottom-left), roller at node 17
                 (bottom-right, Uy restrained only)
    - Loads:     2 × 1 kip ↓ at (20, 0) and (20, 10), ramped via
                 LoadControl from 0 to 10 over 10 steps

Analysis cases:
    1. ``Static`` — 10-step LoadControl, midspan Uy ≈ -0.394 in
    2. ``FreeVibration`` — Transient with preload = case 1, remove
       pattern 1, Newmark (γ=0.5, β=0.25), dt = 0.5 s, 1500 steps,
       βK auto-computed from 2% damping at the 1st mode.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import (
    ElasticIsotropic,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    QuadElement,
    StaticCase,
    TransientCase,
    UnitSystem,
)
from opensees_studio.services import load_project, save_project


# Geometry (inches).
L = 40.0
H = 10.0
THICKNESS = 1.0

# Mesh — nx must be even so a node lands at the midspan.
NX = 16
NY = 4

# Material (kip-in units).
E = 1000.0
NU = 0.25
RHO = 3.0


def _node_id(i: int, j: int) -> int:
    """Row-major node id (matching the Tcl ``block2D`` numbering).

    i = 0..NX column index (along length), j = 0..NY row index (through depth).
    """
    return j * (NX + 1) + i + 1


def _mid_bottom_node_id() -> int:
    """Node at (L/2, 0) — bottom flange midspan where one load attaches."""
    return _node_id(NX // 2, 0)


def _mid_top_node_id() -> int:
    """Node at (L/2, H) — top flange midspan where the other load attaches."""
    return _node_id(NX // 2, NY)


def _right_bottom_node_id() -> int:
    """Bottom-right corner — the roller support."""
    return _node_id(NX, 0)


def build_beam_quad_2d() -> Project:
    dx = L / NX
    dy = H / NY

    nodes: list[Node] = []
    for j in range(NY + 1):
        for i in range(NX + 1):
            nid = _node_id(i, j)
            if nid == 1:
                restraint = (True, True, False, False, False, False)     # pin
            elif nid == _right_bottom_node_id():
                restraint = (False, True, False, False, False, False)    # roller (Uy only)
            else:
                restraint = (False,) * 6
            nodes.append(Node(
                id=nid, name=f"N{nid}",
                coords=(i * dx, j * dy, 0.0),
                restraint=restraint,
            ))

    elements: list[QuadElement] = []
    eid = 1
    for j in range(NY):
        for i in range(NX):
            n1 = _node_id(i, j)            # bottom-left
            n2 = _node_id(i + 1, j)        # bottom-right
            n3 = _node_id(i + 1, j + 1)    # top-right
            n4 = _node_id(i, j + 1)        # top-left  (counter-clockwise)
            elements.append(QuadElement(
                id=eid, name=f"Q{eid}",
                nodes=(n1, n2, n3, n4),
                thickness=THICKNESS,
                material_id=1,
                variant="quad",
                behaviour="PlaneStress2D",
            ))
            eid += 1

    return Project(
        meta=ProjectMeta(
            name="Simply Supported Beam — Quad Elements (OpenSees Ex 6.4)",
            author="OpenSees Examples Manual",
            description=(
                f"{NX}×{NY} plane-stress quad mesh of a {L:.0f}×{H:.0f} deep "
                "beam with two midspan point loads, LoadControl 0→10 in 10 steps."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2, ndf=2,
        nodes=nodes,
        materials=[ElasticIsotropic(id=1, name="Elastic", E=E, nu=NU, rho=RHO)],
        elements=elements,
        time_series=[LinearTimeSeries(id=1, name="Ramp")],
        load_patterns=[PlainLoadPattern(
            id=1, name="MidspanLoad",
            time_series_id=1,
            nodal_loads=[
                NodalLoad(node_id=_mid_bottom_node_id(),
                          forces=(0.0, -1.0, 0.0, 0.0, 0.0, 0.0)),
                NodalLoad(node_id=_mid_top_node_id(),
                          forces=(0.0, -1.0, 0.0, 0.0, 0.0, 0.0)),
            ],
        )],
        analyses=[
            StaticCase(
                id=1, name="Static",
                pattern_ids=[1],
                n_steps=10, load_factor_increment=1.0,
                system="ProfileSPD", constraints="Plain",
                integrator="LoadControl", algorithm="Newton",
                test="EnergyIncr", tolerance=1e-12, max_iter=10,
            ),
            # Free-vibration continuation: runs case 1 to completion,
            # drops the midspan load pattern, sets up 2% βK Rayleigh
            # damping from the 1st mode, then integrates 1500 steps of
            # Newmark (γ=0.5, β=0.25) at dt = 0.5 s.
            TransientCase(
                id=2, name="FreeVibration",
                preload_case_ids=[1],
                remove_patterns=[1],
                pattern_ids=[],
                dt=0.5, n_steps=1500,
                system="BandGeneral", constraints="Plain",
                integrator="Newmark", integrator_params=(0.5, 0.25),
                algorithm="Newton",
                test="EnergyIncr", tolerance=1e-12, max_iter=10,
                rayleigh_mode1_damping=0.02,
            ),
        ],
    )


def main() -> None:
    project = build_beam_quad_2d()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  ndm={project.ndm}, ndf={project.ndf}, "
          f"units={project.meta.units.value}")
    print(f"  {len(project.nodes)} nodes, {len(project.elements)} quads")
    print(f"  Midspan loaded nodes: bottom={_mid_bottom_node_id()}, "
          f"top={_mid_top_node_id()}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
