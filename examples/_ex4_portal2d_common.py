"""Shared builders for OpenSees Example 4 portal-frame variants."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opensees_studio.core import (  # noqa: E402
    AggregatorDOF,
    Concrete02,
    ElasticBeamColumn,
    ElasticSection,
    ElasticUniaxial,
    FiberSection,
    ForceBeamColumn,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    ProjectMeta,
    PushoverCase,
    RectangularPatch,
    SectionAggregator,
    StaticCase,
    Steel01,
    Steel02,
    StraightLayer,
    TransientCase,
    UniformElementLoad,
    UniformExcitationPattern,
    UnitSystem,
)


INCH = 1.0
KIP = 1.0
SEC = 1.0
FT = 12.0 * INCH
KSI = KIP / INCH**2
PSI = KSI / 1000.0
G_ACCEL = 32.2 * FT / SEC**2
PI = math.pi

L_COL = 36.0 * FT
L_BEAM = 42.0 * FT
H_BEAM = 8.0 * FT
B_BEAM = 5.0 * FT
A_BEAM = B_BEAM * H_BEAM
IZ_BEAM = (1.0 / 12.0) * B_BEAM * H_BEAM**3

FC = -4.0 * KSI
E_C = 57.0 * KSI * math.sqrt(-FC / PSI)

N_GRAVITY = 10
GRAVITY_STEP = 1.0 / N_GRAVITY
PUSH_TARGET = 0.1 * L_COL
PUSH_STEP = 0.001 * L_COL
NUM_INT_PTS = 5

SINE_AMPLITUDE = 0.5 * G_ACCEL
SINE_PERIOD = 0.35 * SEC
SINE_DURATION = 3.0 * SEC
GROUND_DT = 0.005 * SEC
ANALYSIS_DT = 0.01 * SEC
ANALYSIS_DURATION = 10.0 * SEC
ANALYSIS_STEPS = int(ANALYSIS_DURATION / ANALYSIS_DT)
DAMPING_RATIO = 0.02

_ROOT = Path(__file__).resolve().parent
REFERENCE_PUSH_TCL = _ROOT / "data" / "Ex4.Portal2D.analyze.Static.Push.tcl.txt"
REFERENCE_SINE_TCL = _ROOT / "data" / "Ex4.Portal2D.analyze.Dynamic.sine.Uniform.tcl.txt"


def sine_accel_values(
    dt: float = GROUND_DT,
    amplitude: float = SINE_AMPLITUDE,
    period: float = SINE_PERIOD,
    duration: float = SINE_DURATION,
) -> list[float]:
    """Sample the Example 4 sine support motion as a PathTimeSeries."""

    omega = 2.0 * PI / period
    n_points = int(round(duration / dt)) + 1
    return [amplitude * math.sin(omega * i * dt) for i in range(n_points)]


def sine_velocity_values(
    dt: float = GROUND_DT,
    amplitude: float = SINE_AMPLITUDE,
    period: float = SINE_PERIOD,
    duration: float = SINE_DURATION,
) -> list[float]:
    """Velocity history consistent with the Tcl ``-vel0`` sine recipe."""

    omega = 2.0 * PI / period
    n_points = int(round(duration / dt)) + 1
    return [-(amplitude / omega) * math.cos(omega * i * dt) for i in range(n_points)]


@dataclass(frozen=True)
class ElasticVariant:
    name: str
    description: str
    weight: float
    h_col: float
    b_col: float
    build_tcl_name: str


@dataclass(frozen=True)
class InelasticSectionVariant(ElasticVariant):
    my_col: float
    phi_y_col: float
    hardening_ratio: float = 0.01


@dataclass(frozen=True)
class FiberVariant(ElasticVariant):
    cover_col: float
    num_bars_col: int
    bar_area_col: float
    eps1_u: float
    eps2_u: float
    lambda_: float
    fy: float
    es: float
    bs: float
    r0: float
    cr1: float
    cr2: float
    n_fib_y: int
    n_fib_z: int


ELASTIC_VARIANT = ElasticVariant(
    name="OpenSees Ex 4 - Portal Frame (Elastic Build)",
    description="Example 4 elastic portal frame with shared gravity, push, and sine-wave support motion.",
    weight=4000.0 * KIP,
    h_col=5.0 * FT,
    b_col=4.0 * FT,
    build_tcl_name="Ex4.Portal2D.build.ElasticElement.tcl.txt",
)

INELASTIC_SECTION_VARIANT = InelasticSectionVariant(
    name="OpenSees Ex 4 - Portal Frame (Inelastic Section Build)",
    description="Example 4 portal frame with aggregated uniaxial inelastic column sections and shared analyses.",
    weight=4000.0 * KIP,
    h_col=5.0 * FT,
    b_col=4.0 * FT,
    build_tcl_name="Ex4.Portal2D.build.InelasticSection.tcl.txt",
    my_col=130000.0 * KIP * INCH,
    phi_y_col=0.65e-4 / INCH,
)

FIBER_VARIANT = FiberVariant(
    name="OpenSees Ex 4 - Portal Frame (Fiber Section Build)",
    description="Example 4 portal frame with fiber-section columns and shared pushover / sine-wave analyses.",
    weight=2000.0 * KIP,
    h_col=5.0 * FT,
    b_col=5.0 * FT,
    build_tcl_name="Ex4.Portal2D.build.InelasticFiberSection.tcl.txt",
    cover_col=6.0 * INCH,
    num_bars_col=10,
    bar_area_col=2.25 * INCH**2,
    eps1_u=-0.003,
    eps2_u=-0.05,
    lambda_=0.1,
    fy=66.8 * KSI,
    es=29000.0 * KSI,
    bs=0.01,
    r0=18.0,
    cr1=0.925,
    cr2=0.15,
    n_fib_y=16,
    n_fib_z=4,
)


def _common_nodes(weight: float) -> list[Node]:
    p_col = weight / 2.0
    mass = p_col / G_ACCEL
    return [
        Node(id=1, name="Base-L", coords=(0.0, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
        Node(id=2, name="Base-R", coords=(L_BEAM, 0.0, 0.0), restraint=(True, True, False, False, False, True)),
        Node(id=3, name="Top-L", coords=(0.0, L_COL, 0.0), mass=(mass, 0.0, 0.0, 0.0, 0.0, 0.0)),
        Node(id=4, name="Top-R", coords=(L_BEAM, L_COL, 0.0), mass=(mass, 0.0, 0.0, 0.0, 0.0, 0.0)),
    ]


def _common_patterns(weight: float) -> tuple[list[LinearTimeSeries | PathTimeSeries], list[PlainLoadPattern | UniformExcitationPattern]]:
    p_col = weight / 2.0
    w_beam = -weight / L_BEAM
    time_series = [
        LinearTimeSeries(id=1, name="Gravity"),
        LinearTimeSeries(id=200, name="Lateral"),
        PathTimeSeries(
            id=400,
            name="Sine-0p5g",
            dt=GROUND_DT,
            values=sine_accel_values(),
            file_path="generated:sine-wave",
        ),
        PathTimeSeries(
            id=401,
            name="SineVel-0p5g",
            dt=GROUND_DT,
            values=sine_velocity_values(),
            file_path="generated:sine-wave-velocity",
        ),
    ]
    patterns = [
        PlainLoadPattern(
            id=1,
            name="Gravity",
            time_series_id=1,
            element_loads=[UniformElementLoad(element_id=3, wy=w_beam)],
        ),
        PlainLoadPattern(
            id=200,
            name="Pushover-X",
            time_series_id=200,
            nodal_loads=[
                NodalLoad(node_id=3, forces=(p_col, 0.0, 0.0, 0.0, 0.0, 0.0)),
                NodalLoad(node_id=4, forces=(p_col, 0.0, 0.0, 0.0, 0.0, 0.0)),
            ],
        ),
        UniformExcitationPattern(
            id=400,
            name="Sine-Uniform-X",
            direction=1,
            accel_series_id=400,
            vel_series_id=401,
        ),
    ]
    return time_series, patterns


def _common_analyses() -> list[StaticCase | PushoverCase | TransientCase]:
    return [
        StaticCase(
            id=1,
            name="Gravity",
            pattern_ids=[1],
            n_steps=N_GRAVITY,
            load_factor_increment=GRAVITY_STEP,
            system="BandGeneral",
            constraints="Plain",
            integrator="LoadControl",
            algorithm="Newton",
            test="NormDispIncr",
            tolerance=1e-8,
            max_iter=6,
        ),
        PushoverCase(
            id=2,
            name="Push",
            preload_case_ids=[1],
            pattern_ids=[200],
            control_node=3,
            control_dof=1,
            target_disp=PUSH_TARGET,
            step_size=PUSH_STEP,
            base_nodes=[1, 2],
            system="BandGeneral",
            constraints="Plain",
            algorithm="Newton",
            test="EnergyIncr",
            tolerance=1e-8,
            max_iter=6,
        ),
        TransientCase(
            id=3,
            name="Sine-Uniform",
            preload_case_ids=[1],
            pattern_ids=[400],
            dt=ANALYSIS_DT,
            n_steps=ANALYSIS_STEPS,
            system="BandGeneral",
            constraints="Transformation",
            integrator="Newmark",
            integrator_params=(0.5, 0.25),
            algorithm="ModifiedNewton",
            test="EnergyIncr",
            tolerance=1e-8,
            max_iter=10,
            rayleigh_mode1_damping=DAMPING_RATIO,
        ),
    ]


def build_ex4_portal2d_elastic_element() -> Project:
    a_col = ELASTIC_VARIANT.b_col * ELASTIC_VARIANT.h_col
    iz_col = (1.0 / 12.0) * ELASTIC_VARIANT.b_col * ELASTIC_VARIANT.h_col**3
    time_series, patterns = _common_patterns(ELASTIC_VARIANT.weight)
    return Project(
        meta=ProjectMeta(
            name=ELASTIC_VARIANT.name,
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=ELASTIC_VARIANT.description,
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=_common_nodes(ELASTIC_VARIANT.weight),
        sections=[
            ElasticSection(id=1, name="Columns", E=E_C, A=a_col, Iz=iz_col, Iy=iz_col, G=1.0, J=1.0),
            ElasticSection(id=2, name="Beam", E=E_C, A=A_BEAM, Iz=IZ_BEAM, Iy=IZ_BEAM, G=1.0, J=1.0),
        ],
        elements=[
            ElasticBeamColumn(id=1, name="Col-L", nodes=(1, 3), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=2, name="Col-R", nodes=(2, 4), section_id=1, geom_transf="Linear"),
            ElasticBeamColumn(id=3, name="Beam", nodes=(3, 4), section_id=2, geom_transf="Linear"),
        ],
        time_series=time_series,
        load_patterns=patterns,
        analyses=_common_analyses(),
    )


def build_ex4_portal2d_inelastic_section() -> Project:
    a_col = INELASTIC_SECTION_VARIANT.b_col * INELASTIC_SECTION_VARIANT.h_col
    ei_col_cracked = INELASTIC_SECTION_VARIANT.my_col / INELASTIC_SECTION_VARIANT.phi_y_col
    time_series, patterns = _common_patterns(INELASTIC_SECTION_VARIANT.weight)
    return Project(
        meta=ProjectMeta(
            name=INELASTIC_SECTION_VARIANT.name,
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=INELASTIC_SECTION_VARIANT.description,
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=_common_nodes(INELASTIC_SECTION_VARIANT.weight),
        materials=[
            Steel01(
                id=2,
                name="Flexural-Steel01",
                Fy=INELASTIC_SECTION_VARIANT.my_col,
                E0=ei_col_cracked,
                b=INELASTIC_SECTION_VARIANT.hardening_ratio,
            ),
            ElasticUniaxial(id=3, name="Axial-Elastic", E=E_C * a_col),
        ],
        sections=[
            SectionAggregator(
                id=1,
                name="Column-Section",
                pairings=[
                    AggregatorDOF(material_id=3, dof="P"),
                    AggregatorDOF(material_id=2, dof="Mz"),
                ],
            ),
            ElasticSection(id=2, name="Beam", E=E_C, A=A_BEAM, Iz=IZ_BEAM, Iy=IZ_BEAM, G=1.0, J=1.0),
        ],
        elements=[
            ForceBeamColumn(id=1, name="Col-L", nodes=(1, 3), section_id=1, integration_points=NUM_INT_PTS, geom_transf="Linear"),
            ForceBeamColumn(id=2, name="Col-R", nodes=(2, 4), section_id=1, integration_points=NUM_INT_PTS, geom_transf="Linear"),
            ForceBeamColumn(id=3, name="Beam", nodes=(3, 4), section_id=2, integration_points=NUM_INT_PTS, geom_transf="Linear"),
        ],
        time_series=time_series,
        load_patterns=patterns,
        analyses=_common_analyses(),
    )


def build_ex4_portal2d_inelastic_fiber_section() -> Project:
    cover_y = FIBER_VARIANT.h_col / 2.0
    cover_z = FIBER_VARIANT.b_col / 2.0
    core_y = cover_y - FIBER_VARIANT.cover_col
    core_z = cover_z - FIBER_VARIANT.cover_col
    ft_u = -0.14 * FC
    ets = ft_u / 0.002
    time_series, patterns = _common_patterns(FIBER_VARIANT.weight)
    return Project(
        meta=ProjectMeta(
            name=FIBER_VARIANT.name,
            author="OpenSees Wiki / Silvia Mazzoni & Frank McKenna",
            description=FIBER_VARIANT.description,
            units=UnitSystem.US_IN_KIP,
        ),
        ndm=2,
        ndf=3,
        nodes=_common_nodes(FIBER_VARIANT.weight),
        materials=[
            Concrete02(
                id=1,
                name="Cover-Concrete",
                fpc=FC,
                epsc0=FIBER_VARIANT.eps1_u,
                fpcu=0.2 * FC,
                epsU=FIBER_VARIANT.eps2_u,
                lambda_=FIBER_VARIANT.lambda_,
                ft=ft_u,
                Ets=ets,
            ),
            Steel02(
                id=2,
                name="Rebar-Steel02",
                Fy=FIBER_VARIANT.fy,
                E0=FIBER_VARIANT.es,
                b=FIBER_VARIANT.bs,
                R0=FIBER_VARIANT.r0,
                cR1=FIBER_VARIANT.cr1,
                cR2=FIBER_VARIANT.cr2,
            ),
        ],
        sections=[
            FiberSection(
                id=1,
                name="Column-Fiber-Section",
                patches=[
                    RectangularPatch(
                        material_id=1,
                        n_fib_y=FIBER_VARIANT.n_fib_y,
                        n_fib_z=FIBER_VARIANT.n_fib_z,
                        y_i=-cover_y,
                        z_i=-cover_z,
                        y_j=cover_y,
                        z_j=cover_z,
                    ),
                ],
                layers=[
                    StraightLayer(
                        material_id=2,
                        n_bars=FIBER_VARIANT.num_bars_col,
                        bar_area=FIBER_VARIANT.bar_area_col,
                        y_start=-core_y,
                        z_start=core_z,
                        y_end=-core_y,
                        z_end=-core_z,
                    ),
                    StraightLayer(
                        material_id=2,
                        n_bars=FIBER_VARIANT.num_bars_col,
                        bar_area=FIBER_VARIANT.bar_area_col,
                        y_start=core_y,
                        z_start=core_z,
                        y_end=core_y,
                        z_end=-core_z,
                    ),
                ],
            ),
            ElasticSection(id=2, name="Beam", E=E_C, A=A_BEAM, Iz=IZ_BEAM, Iy=IZ_BEAM, G=1.0, J=1.0),
        ],
        elements=[
            ForceBeamColumn(id=1, name="Col-L", nodes=(1, 3), section_id=1, integration_points=NUM_INT_PTS, geom_transf="Linear"),
            ForceBeamColumn(id=2, name="Col-R", nodes=(2, 4), section_id=1, integration_points=NUM_INT_PTS, geom_transf="Linear"),
            ForceBeamColumn(id=3, name="Beam", nodes=(3, 4), section_id=2, integration_points=NUM_INT_PTS, geom_transf="Linear"),
        ],
        time_series=time_series,
        load_patterns=patterns,
        analyses=_common_analyses(),
    )
