"""
Material Tester service -- headless uniaxial constitutive law probe.

Applies a monotonic or cyclic strain protocol to a minimal single-element
OpenSeesPy model (two co-located nodes, one zero-length element, one fixed
DOF, displacement-controlled loading) and returns the complete stress-strain
history.  Every call is self-contained: ``wipe()`` is called unconditionally in
a ``finally`` block, so OpenSees state never leaks into subsequent calls or
into the ``OpenSeesRunner``.

Protocol semantics
------------------
``LoadProtocol.kind == "monotonic"``
    Strain swept from 0 -> *max_compressive* (then -> *max_tensile* if > 0),
    using *n_steps_per_branch* uniform displacement increments per branch.

``LoadProtocol.kind == "cyclic"``
    Each :class:`CyclicSegment` entry drives *n_cycles* complete
    excursions: 0 -> *compressive_peak* -> *tensile_peak* -> 0.
    Segments are executed in order; the material state is NOT reset between
    segments (consistent with a continuous experimental loading history).

Sign convention
---------------
* Compressive strain and stress are **negative** (OpenSeesPy / OpenSees
  convention).
* The returned stress is the material response stress: negative for
  compression, positive for tension.

Attribution
-----------
The single-element material-test workflow mirrors the approach used in
**gidopensees** by G. Ntinolazos, AUTh Laboratory of R/C and Masonry
Structures (GPL-3.0).  This Python re-implementation forms the headless
service layer for a future Material Tester dialog in OpenSees Studio.
OpenSees Studio as a whole is licensed under AGPL-3.0.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveInt, model_validator

from opensees_studio.core.materials import (
    Concrete01,
    Concrete02,
    Concrete04,
    ElasticIsotropic,
    ElasticPP,
    ElasticUniaxial,
    HystereticMaterial,
    Steel01,
    Steel02,
)

# ---- protocol models -------------------------------------------------------


class CyclicSegment(BaseModel):
    """One symmetric or asymmetric excursion group in a cyclic protocol.

    Each group is applied *n_cycles* times, each time going:
    current -> *compressive_peak* -> *tensile_peak* -> 0.
    """

    compressive_peak: float = Field(..., lt=0.0, description="Target compressive strain (negative).")
    tensile_peak: float = Field(..., gt=0.0, description="Target tensile strain (positive).")
    n_cycles: PositiveInt = Field(1, description="Number of complete excursions to run.")


class LoadProtocol(BaseModel):
    """Strain-driven loading history for a material test.

    Attributes
    ----------
    kind:
        ``"monotonic"`` -- single ramp; ``"cyclic"`` -- uses *cycles*.
    max_compressive:
        Peak compressive strain (negative) for monotonic protocols.
    max_tensile:
        Peak tensile strain (positive) for monotonic protocols; ``0``
        for compression-only tests.
    n_steps_per_branch:
        Displacement increments per straight-line branch between two
        consecutive waypoints.  More steps = smoother curve at the cost
        of run time.
    cycles:
        Required for ``kind="cyclic"``; list of :class:`CyclicSegment`.
    """

    kind: Literal["monotonic", "cyclic"]
    max_compressive: float = Field(..., lt=0.0)
    max_tensile: float = Field(0.0, ge=0.0)
    n_steps_per_branch: int = Field(50, ge=2)
    cycles: list[CyclicSegment] | None = None

    @model_validator(mode="after")
    def _cyclic_needs_segments(self) -> LoadProtocol:
        if self.kind == "cyclic" and not self.cycles:
            raise ValueError("'cycles' must be provided when kind='cyclic'.")
        return self


class MaterialTestResult(BaseModel):
    """Stress-strain history from a completed material test run."""

    strain: list[float]
    stress: list[float]
    material_name: str
    protocol: LoadProtocol


# ---- internal helpers ------------------------------------------------------


def _waypoints(protocol: LoadProtocol) -> list[float]:
    """Return the ordered strain waypoints implied by *protocol*.

    The first entry is always 0.0 (initial unstressed state).  Consecutive
    pairs define the branches that DisplacementControl will traverse.
    """
    pts: list[float] = [0.0]
    if protocol.kind == "monotonic":
        pts.append(protocol.max_compressive)
        if protocol.max_tensile > 0.0:
            pts.append(protocol.max_tensile)
    else:  # cyclic
        for seg in protocol.cycles or []:
            for _ in range(seg.n_cycles):
                pts.append(seg.compressive_peak)
                pts.append(seg.tensile_peak)
                pts.append(0.0)
    return pts


def _emit_uniaxial(ops: Any, mat: Any) -> None:
    """Emit the ``uniaxialMaterial`` command for *mat* on *ops*.

    Mirrors ``OpenSeesRunner._emit_material`` for all uniaxial types.
    :class:`~opensees_studio.core.materials.ElasticIsotropic` is an nD
    material and raises :exc:`TypeError`.
    """
    match mat:
        case ElasticIsotropic():
            raise TypeError(
                "ElasticIsotropic is a 3-D nDMaterial and cannot be tested "
                "as a uniaxial material."
            )
        case ElasticUniaxial():
            args: list[Any] = [mat.E]
            if mat.eta or mat.Eneg is not None:
                args.append(mat.eta)
            if mat.Eneg is not None:
                args.append(mat.Eneg)
            ops.uniaxialMaterial("Elastic", mat.id, *args)
        case Steel01():
            args = [mat.Fy, mat.E0, mat.b]
            if mat.a1 is not None:
                args.extend([mat.a1, mat.a2, mat.a3, mat.a4])
            ops.uniaxialMaterial("Steel01", mat.id, *args)
        case Steel02():
            ops.uniaxialMaterial(
                "Steel02", mat.id, mat.Fy, mat.E0, mat.b, mat.R0, mat.cR1, mat.cR2,
            )
        case Concrete01():
            ops.uniaxialMaterial(
                "Concrete01", mat.id, mat.fpc, mat.epsc0, mat.fpcu, mat.epsU,
            )
        case Concrete02():
            ops.uniaxialMaterial(
                "Concrete02", mat.id,
                mat.fpc, mat.epsc0, mat.fpcu, mat.epsU,
                mat.lambda_, mat.ft, mat.Ets,
            )
        case Concrete04():
            args = [mat.fpc, mat.epsc0, mat.epscu, mat.Ec]
            if mat.fct is not None:
                args.extend([mat.fct, mat.et])
                if mat.beta is not None:
                    args.append(mat.beta)
            ops.uniaxialMaterial("Concrete04", mat.id, *args)
        case ElasticPP():
            args = [mat.E, mat.epsy_pos]
            if mat.epsy_neg is not None or mat.eps0 != 0.0:
                args.append(mat.epsy_neg if mat.epsy_neg is not None else -mat.epsy_pos)
                args.append(mat.eps0)
            ops.uniaxialMaterial("ElasticPP", mat.id, *args)
        case HystereticMaterial():
            ops.uniaxialMaterial(
                "Hysteretic", mat.id,
                mat.s1p, mat.e1p, mat.s2p, mat.e2p, mat.s3p, mat.e3p,
                mat.s1n, mat.e1n, mat.s2n, mat.e2n, mat.s3n, mat.e3n,
                mat.px, mat.py, mat.d1, mat.d2, mat.beta,
            )
        case _:
            raise TypeError(f"Unsupported material type: {type(mat).__name__}")


# ---- public API ------------------------------------------------------------


def test_uniaxial_material(
    material: Any,
    protocol: LoadProtocol,
    *,
    ops_module: Any | None = None,
) -> MaterialTestResult:
    """Run *material* through *protocol* and return the stress-strain history.

    The function is **safe to call repeatedly and interleaved** with normal
    ``OpenSeesRunner`` analyses: it unconditionally calls ``wipe()`` on entry
    (to clear any prior state) and again in a ``finally`` block on exit (to
    leave a clean slate for the next caller).

    Parameters
    ----------
    material:
        Any uniaxial material from ``opensees_studio.core``.
        :class:`~opensees_studio.core.materials.ElasticIsotropic` raises
        :exc:`TypeError` because it is a 3-D nD material.
    protocol:
        Strain-driven loading history.
    ops_module:
        Injectable ``openseespy.opensees`` module.  Defaults to the real
        module; override with a mock for unit testing.

    Returns
    -------
    MaterialTestResult
        ``strain`` and ``stress`` lists have the same length
        (``n_steps_per_branch x number_of_branches``).

    Raises
    ------
    TypeError
        If *material* is :class:`~opensees_studio.core.materials.ElasticIsotropic`.
    RuntimeError
        If OpenSeesPy fails to converge at any analysis step.
    """
    if ops_module is None:
        import openseespy.opensees as _ops_default
        ops_module = _ops_default

    ops = ops_module
    mat_name = getattr(material, "name", None) or str(getattr(material, "type", type(material).__name__))

    try:
        # Clear any leftover OpenSees state from a prior call or runner.
        ops.wipe()
        ops.model("basic", "-ndm", 1, "-ndf", 1)

        # Two co-located nodes; node 1 is fully fixed, node 2 is free.
        ops.node(1, 0.0)
        ops.node(2, 0.0)
        ops.fix(1, 1)

        # Register the material and attach it to a zero-length spring element.
        _emit_uniaxial(ops, material)
        ops.element("zeroLength", 1, 1, 2, "-mat", material.id, "-dir", 1)

        # Unit load at the free node drives the displacement-control integrator.
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        ops.load(2, 1.0)

        ops.system("BandGeneral")
        ops.constraints("Plain")
        ops.numberer("RCM")
        ops.test("NormDispIncr", 1e-12, 200)
        ops.algorithm("Newton")
        ops.analysis("Static")

        waypoints = _waypoints(protocol)
        strains: list[float] = []
        stresses: list[float] = []
        current = 0.0

        for target in waypoints[1:]:
            if target == current:
                continue
            delta = (target - current) / protocol.n_steps_per_branch
            ops.integrator("DisplacementControl", 2, 1, delta)
            for _ in range(protocol.n_steps_per_branch):
                ok = ops.analyze(1)
                if ok != 0:
                    raise RuntimeError(
                        f"Material tester failed to converge near "
                        f"strain={ops.nodeDisp(2, 1):.4g} "
                        f"(branch target={target:.4g})."
                    )
                strains.append(ops.nodeDisp(2, 1))
                # Reaction at fixed node 1 = -stress (equilibrium analysis).
                # Negate to obtain the material stress with correct sign.
                ops.reactions()
                stresses.append(-ops.nodeReaction(1, 1))
            current = target

        return MaterialTestResult(
            strain=strains,
            stress=stresses,
            material_name=mat_name,
            protocol=protocol,
        )

    finally:
        # Always restore clean OpenSees state so subsequent runner calls
        # or further material tests start from a blank domain.
        ops.wipe()


# Prevent pytest from treating this service function as a test case.
test_uniaxial_material.__test__ = False  # type: ignore[attr-defined]
