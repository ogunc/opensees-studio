"""Base-isolated portal frame: OpenSees Example 1b frame on two elastomeric bearings.

The elastic portal frame of Example 1b (inch, kip units) stands on two
``elastomericBearingPlasticity`` isolators instead of fixed supports. The
ground nodes are fixed, the isolated base nodes are coincident with them,
carry a base-slab mass, have their rotation restrained and share their X
displacement through an equalDOF (a stiff base slab), and the BM68elc record (in g, scaled to in/s^2 with the project
unit system) drives a uniform excitation after a gravity preload.

Isolator design (per bearing): the frame weight is about 2000 kip per
column line, so Qd = 100 kip (5 percent of the weight), post-yield period
about 2.5 s with the tributary mass gives alpha1 Kinit = 45 kip/in,
alpha1 = 0.1, Kinit = 450 kip/in and a yield displacement of 0.247 in.

Run from the repository root:

    python examples/isolated_portal2d.py

Produces ``examples/isolated_portal2d.osmodel``.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    ElastomericBearingPlasticityElement,
    EqualDOFConstraint,
    GroundMotionRecord,
    LinearTimeSeries,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    StaticCase,
    TransientCase,
    UniformElementLoad,
    UniformExcitationPattern,
    UnitSystem,
    gravity,
    import_record,
)
from opensees_studio.services import load_project, save_project
from opensees_studio.services.peer_record import parse_plain_values

L_BEAM = 504.0
L_COL = 432.0
TOP_MASS = 5.18  # kip s^2/in per top node (Example 1b)
BASE_MASS = 2.0  # kip s^2/in per isolated base node (base slab)

A_COL = 3_600_000_000.0
IZ_COL = 1_080_000.0
A_BEAM = 5_760_000_000.0
IZ_BEAM = 4_423_680.0
E_MODULUS = 4227.0

GRAVITY_W = -7.94  # kip/in on the beam (Example 1b)

# Bearing shear model, per isolator
K_INIT = 450.0  # kip/in
QD = 100.0  # kip
ALPHA1 = 0.1
# Axial and rotational responses of the bearing (uniaxial Elastic: force per deformation)
K_AXIAL = 1.0e5  # kip/in
K_ROT = 1.0e4  # kip in/rad

GROUND_DT = 0.01
# BM68elc is in g; the project unit system gives g in in/s^2.
GROUND_FACTOR = gravity(UnitSystem.US_IN_KIP)
ANALYSIS_DT = 0.02
ANALYSIS_STEPS = 1000
DAMPING_RATIO = 0.02

_ROOT = Path(__file__).resolve().parent
GROUND_MOTION_FILE = _ROOT / "data" / "BM68elc.acc"
GM_RECORD_ID = 1

NODE_GROUND_L, NODE_GROUND_R = 1, 2
NODE_TOP_L, NODE_TOP_R = 3, 4
NODE_BASE_L, NODE_BASE_R = 5, 6
BEARING_L, BEARING_R = 4, 5


def _ground_motion_record() -> GroundMotionRecord:
    record, _values = import_record(
        GROUND_MOTION_FILE,
        base_dir=_ROOT,
        record_id=GM_RECORD_ID,
        name="BM68elc",
        format="single_column",
        dt=GROUND_DT,
        accel_units="g",
        source_note="Bundled OpenSees example record BM68elc.",
    )
    return record


def _bearing(
    element_id: int, ground: int, base: int, name: str
) -> ElastomericBearingPlasticityElement:
    return ElastomericBearingPlasticityElement(
        id=element_id,
        name=name,
        nodes=(ground, base),
        k_init=K_INIT,
        qd=QD,
        alpha1=ALPHA1,
        p_material_id=1,
        mz_material_id=2,
    )


def build_isolated_portal2d() -> Project:
    values = parse_plain_values(GROUND_MOTION_FILE)
    fixed = (True, True, False, False, False, True)
    # The isolated base nodes rotate with the stiff base slab: Rz restrained, X and Y free.
    slab = (False, False, False, False, False, True)
    return Project(
        meta=ProjectMeta(
            name="Base-isolated portal frame (Ex 1b on elastomeric bearings)",
            author="OpenSees Studio examples",
            description=(
                "Example 1b elastic portal frame on two elastomericBearingPlasticity "
                "isolators: gravity preload then the BM68elc record as uniform excitation."
            ),
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=NODE_GROUND_L, name="Ground-L", coords=(0.0, 0.0, 0.0), restraint=fixed),
            Node(id=NODE_GROUND_R, name="Ground-R", coords=(L_BEAM, 0.0, 0.0), restraint=fixed),
            Node(
                id=NODE_TOP_L,
                name="Top-L",
                coords=(0.0, L_COL, 0.0),
                mass=(TOP_MASS, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
            Node(
                id=NODE_TOP_R,
                name="Top-R",
                coords=(L_BEAM, L_COL, 0.0),
                mass=(TOP_MASS, 0.0, 0.0, 0.0, 0.0, 0.0),
            ),
            Node(
                id=NODE_BASE_L,
                name="Base-L",
                coords=(0.0, 0.0, 0.0),
                mass=(BASE_MASS, 0.0, 0.0, 0.0, 0.0, 0.0),
                restraint=slab,
            ),
            Node(
                id=NODE_BASE_R,
                name="Base-R",
                coords=(L_BEAM, 0.0, 0.0),
                mass=(BASE_MASS, 0.0, 0.0, 0.0, 0.0, 0.0),
                restraint=slab,
            ),
        ],
        # The base slab ties the two isolated nodes in X: the gravity thrust of the
        # beam is carried by the slab, not by the isolators' shear stiffness.
        mp_constraints=[
            EqualDOFConstraint(retained_node=NODE_BASE_L, constrained_node=NODE_BASE_R, dofs=(1,))
        ],
        materials=[
            ElasticUniaxial(id=1, name="Bearing axial", E=K_AXIAL),
            ElasticUniaxial(id=2, name="Bearing rotation", E=K_ROT),
        ],
        sections=[
            ElasticSection(
                id=1, name="Column", E=E_MODULUS, A=A_COL, Iz=IZ_COL, Iy=IZ_COL, G=1.0, J=1.0
            ),
            ElasticSection(
                id=2, name="Beam", E=E_MODULUS, A=A_BEAM, Iz=IZ_BEAM, Iy=IZ_BEAM, G=1.0, J=1.0
            ),
        ],
        elements=[
            ElasticBeamColumn(id=1, name="Col-L", nodes=(NODE_BASE_L, NODE_TOP_L), section_id=1),
            ElasticBeamColumn(id=2, name="Col-R", nodes=(NODE_BASE_R, NODE_TOP_R), section_id=1),
            ElasticBeamColumn(id=3, name="Beam", nodes=(NODE_TOP_L, NODE_TOP_R), section_id=2),
            _bearing(BEARING_L, NODE_GROUND_L, NODE_BASE_L, "Isolator-L"),
            _bearing(BEARING_R, NODE_GROUND_R, NODE_BASE_R, "Isolator-R"),
        ],
        ground_motions=[_ground_motion_record()],
        time_series=[
            LinearTimeSeries(id=1, name="Gravity"),
            PathTimeSeries(
                id=2,
                name="BM68elc",
                dt=GROUND_DT,
                factor=GROUND_FACTOR,
                values=values,
                record_id=GM_RECORD_ID,
                file_path=str(GROUND_MOTION_FILE.name),
            ),
        ],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                name="Gravity",
                time_series_id=1,
                element_loads=[UniformElementLoad(element_id=3, wy=GRAVITY_W)],
            ),
            UniformExcitationPattern(id=2, name="GroundMotion-X", direction=1, accel_series_id=2),
        ],
        analyses=[
            StaticCase(
                id=1,
                name="Gravity",
                pattern_ids=[1],
                n_steps=10,
                load_factor_increment=0.1,
                system="BandGeneral",
                constraints="Transformation",
                integrator="LoadControl",
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-8,
                max_iter=10,
            ),
            TransientCase(
                id=2,
                name="Earthquake",
                preload_case_ids=[1],
                pattern_ids=[2],
                dt=ANALYSIS_DT,
                n_steps=ANALYSIS_STEPS,
                system="BandGeneral",
                constraints="Transformation",
                integrator="Newmark",
                integrator_params=(0.5, 0.25),
                algorithm="Newton",
                test="NormDispIncr",
                tolerance=1e-8,
                max_iter=20,
                rayleigh_mode1_damping=DAMPING_RATIO,
            ),
        ],
    )


def main() -> None:
    project = build_isolated_portal2d()
    project.validate_references()
    bearing = project.element(BEARING_L)
    print(f"Built '{project.meta.name}'")
    print(f"  Isolators: Kinit {K_INIT} kip/in, Qd {QD} kip, alpha1 {ALPHA1}")
    print(
        f"  Yield displacement {bearing.yield_displacement:.4f} in, yield force {bearing.yield_force:.2f} kip"
    )
    print(f"  Ground motion file: {GROUND_MOTION_FILE.name}, factor = {GROUND_FACTOR}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
