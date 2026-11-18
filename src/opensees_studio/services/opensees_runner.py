"""OpenSees command translator and analysis executor.

The runner is a thin, deterministic translator from a validated
:class:`Project` to OpenSeesPy commands. It owns no domain state; it
operates on the project passed to its constructor.

Three usage patterns:

    runner = OpenSeesRunner(project)
    runner.build()                                  # construct model only
    results = runner.run(case)                      # build + analyze
    results = runner.run(case, results_dir=path)    # transient: HDF5 here

Testability is paramount. The ``ops`` module is injected (default:
``openseespy.opensees``). Unit tests pass a ``Mock()`` and assert the
exact command sequence — no OpenSees install needed for translation
correctness.

Command order (enforced; reordering is a runtime error in OpenSees):

    wipe → model → node × N → fix × N
    → equalDOF / rigidDiaphragm / rigidLink → mass × N
    → uniaxialMaterial / nDMaterial × M
    → frictionModel × F
    → section × S
    → geomTransf × G  (auto-allocated for frame elements)
    → element × E
    → timeSeries × T
    → pattern × P  (with nested load × L per pattern)
    → recorder × R  (transient only)
    → system / numberer / constraints / integrator / algorithm / test / analysis
    → analyze
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np

from opensees_studio.core import (
    BEARING_CLASSES,
    SLIDING_BEARING_CLASSES,
    BeamWithHingesElement,
    CatalogMaterial,
    ConstantTimeSeries,
    CorotTrussElement,
    CoulombFriction,
    DispBeamColumn,
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    FiberSection,
    ForceBeamColumn,
    ImposedSupportMotionPattern,
    InfluenceLineCase,
    LayeredShellSection,
    LinearTimeSeries,
    ModalCase,
    MVLEMElement,
    NodalLoad,
    NonprismaticSection,
    PathTimeSeries,
    PlainLoadPattern,
    PlateFiberSection,
    PointElementLoad,
    Project,
    PulseTimeSeries,
    PushoverCase,
    QuadElement,
    RectangularTimeSeries,
    ResponseSpectrumCase,
    SectionAggregator,
    ShellMITC4Element,
    StaticCase,
    TransientCase,
    TriangleTimeSeries,
    TrigTimeSeries,
    TripleFrictionPendulumElement,
    TrussElement,
    TwoNodeLinkElement,
    UniformExcitationPattern,
    VelDependentFriction,
    VelNormalFrcDepFriction,
    ZeroLengthElement,
    ZeroLengthSectionElement,
)
from opensees_studio.core.analysis import test_args, transient_integrator_args
from opensees_studio.core.area_loads import pattern_distributed_loads, surface_nodal_loads
from opensees_studio.core.custom_commands import block_tag_base
from opensees_studio.core.diaphragms import (
    auto_fixed_slots,
    constrained_node_ids,
    retained_in_plane_slots,
)
from opensees_studio.core.frame_members import (
    ClearPiece,
    ClearPoint,
    gauss_point_loads,
    split_member_loads,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes, frame_vecxz
from opensees_studio.core.mass_source import effective_nodal_masses
from opensees_studio.core.materials.library import materials_in_emission_order
from opensees_studio.core.modal import (
    SOLVER_AUTO,
    dof_indices,
    free_dof_count,
    normalize_mode_sign,
    orthogonalize_degenerate_modes,
    resolve_modal_solver,
)
from opensees_studio.core.modal_combination import DEFAULT_MODAL_DAMPING, closely_spaced_pairs
from opensees_studio.core.plane import dof_signs, to_solver_coords, to_solver_vector3
from opensees_studio.core.section_cuts import cut_resultant, section_cuts
from opensees_studio.core.self_weight import nodal_self_weight_loads, self_weight_loads
from opensees_studio.core.storey_results import cut_force, storey_cuts
from opensees_studio.core.thermal import equivalent_nodal_loads, fixed_end_forces
from opensees_studio.diagnostics.performance import perf
from opensees_studio.services.catalog_emitters import emit_catalog_material
from opensees_studio.services.frame_members import FramePlan, plan_frame_members
from opensees_studio.services.material_emitters import emit_material
from opensees_studio.services.opensees_io import (
    check_recorder_output,
    load_recorder_table,
    place_files,
    staging_dir,
)
from opensees_studio.services.results import (
    InfluenceLineResults,
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)

# Derived-series tag block: the runner materialises the velocity companion of an
# ImposedSupportMotion displacement record as its own Path series. The tag lives
# far above any hand-authored model id and is collision-checked at emission.
_IMPOSED_VEL_TS_OFFSET = 900_000

SKIP_BEARING_ORIENT_ENV = "OPENSEES_STUDIO_TEST_SKIP_BEARING_ORIENT"
"""Tests only: ``1`` leaves ``-orient`` off bearings, so OpenSees itself hard-exits on a
zero-length bearing (a real solver crash for the crash-reporting tests)."""


# ─────────────────────── DOF-index helper ───────────────────────
def _dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
    """Map (ndm, ndf) onto positions in the canonical 6-DOF storage (see ``core.modal``)."""
    return dof_indices(ndm, ndf)


# ─────────────────────── runner ───────────────────────
_MODAL_STATIC_CASE = SimpleNamespace(constraints="Plain")
"""What the constraint-handler choice reads of a case, for the modal static solves."""


class OpenSeesRunner:
    """Translator + executor. Instantiate with a project, then ``run(case)``."""

    def __init__(
        self,
        project: Project,
        ops_module: Any | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """
        Args:
            project: The model to translate.
            ops_module: ``openseespy.opensees`` by default; override with a
                mock in tests to verify the emitted command sequence
                without invoking the real solver.
            on_progress: Called as ``(completed_steps, total_steps)`` after
                every converged step of a stepped analysis (static,
                pushover, transient). The analysis CLI turns these into
                progress lines.
        """
        if ops_module is None:
            import openseespy.opensees as _default_ops  # local import for testability

            ops_module = _default_ops
        # The solver module is duck-typed at runtime (and a mock in the tests):
        # `Any` is the honest type, and `None` never survives this line.
        self._ops: Any = ops_module
        self._on_progress = on_progress
        self.project = project
        self._dof_idx: tuple[int, ...] = _dof_indices(project.ndm, project.ndf)
        # OpenSees value -> global value of each DOF: -1 on a 2D rotation (core.plane).
        self._dof_sign = np.array(dof_signs(project.ndm, project.ndf), dtype=float)
        self._geom_transf_tags: dict[str, int] = {}
        self._element_geom_transf_tag: dict[int, int] = {}
        self._node_mass: dict[int, np.ndarray] = {}
        self._frame_plan = FramePlan()

    # ─────────────────────── public API ───────────────────────
    def _progress(self, completed: int, total: int) -> None:
        if self._on_progress is not None:
            self._on_progress(completed, total)

    def build(self) -> None:
        """Emit all model-construction commands. Idempotent (wipes first)."""
        self.project.validate_references()
        plan = self._frame_plan = plan_frame_members(self.project)

        ops = self._ops
        # Only the solver itself has the state; a recorder (script export) or a mock must not
        # see the commands.
        if (
            isinstance(ops, ModuleType)
            and (self.project.ndm, self.project.ndf) == (2, 3)
            and any(isinstance(el, TrussElement) for el in self.project.elements)
        ):
            self._clear_truss_scratch()
        ops.wipe()
        ops.model("basic", "-ndm", self.project.ndm, "-ndf", self.project.ndf)

        for node in self.project.nodes:
            self._emit_node(node)
        # Hidden nodes of the frame releases (see services/frame_members.py).
        for extra in plan.nodes:
            ops.node(extra.tag, *extra.coords)
        for ground in plan.grounds:
            ops.fix(ground, *([1] * self.project.ndf))
        # A diaphragm's floating retained node has no stiffness out of its
        # plane: those DOFs are fixed together with the node's own restraint.
        auto_fixed = auto_fixed_slots(self.project)
        for node in self.project.nodes:
            fixed_slots = auto_fixed.get(node.id, set())
            if node.is_restrained or fixed_slots:
                self._emit_fix(node, fixed_slots)
        for mp in self.project.mp_constraints:
            self._emit_mp_constraint(mp)
        for diaphragm in self.project.diaphragms:
            self._ops.rigidDiaphragm(
                diaphragm.perp_dirn,
                diaphragm.retained_node,
                *constrained_node_ids(self.project, diaphragm),
            )
        for link in self.project.rigid_links:
            self._ops.rigidLink(link.kind, link.retained_node, link.constrained_node)
        for retained, constrained in plan.rigid_links:
            ops.rigidLink("beam", retained, constrained)
        for retained, constrained, dofs in plan.equal_dofs:
            ops.equalDOF(retained, constrained, *dofs)

        # Mass: the typed nodal mass plus the mass source; emit only if any non-zero
        self._node_mass = effective_nodal_masses(self.project)
        for node in self.project.nodes:
            if np.any(self._node_mass[node.id]):
                self._emit_mass(node)

        for material in materials_in_emission_order(self.project.materials):
            self._emit_material(material)
        self._run_custom_commands("after_materials")
        for spring in plan.springs:
            for mat_tag, k in zip(spring.material_tags, spring.stiffnesses, strict=True):
                ops.uniaxialMaterial("Elastic", mat_tag, k)
        for friction in self.project.friction_models:
            self._emit_friction_model(friction)

        # Pre-compute: FiberSection id → torsion material id, sourced from any
        # SectionAggregator that wraps the fiber section with a T pairing.
        # Used by _emit_section to satisfy OpenSees FiberSection3d's torsion
        # requirement when GJ is not set directly on the FiberSection.
        self._fiber_torsion_mat: dict[int, int] = {}
        for sec in self.project.sections:
            if isinstance(sec, SectionAggregator) and sec.section_id is not None:
                for pair in sec.pairings:
                    if pair.dof == "T":
                        self._fiber_torsion_mat[sec.section_id] = pair.material_id

        for section in self.project.sections:
            self._emit_section(section)
        for derived in plan.sections:
            ops.section("Elastic", derived.tag, *derived.args)

        # Geometric transformations needed by frame elements
        self._allocate_and_emit_geom_transfs()

        for element in self.project.elements:
            self._emit_element(element)
        for spring in plan.springs:
            ops.element(
                "zeroLength",
                spring.tag,
                spring.node_a,
                spring.node_b,
                "-mat",
                *spring.material_tags,
                "-dir",
                *spring.dirs,
                "-orient",
                *spring.orient,
            )
        self._run_custom_commands("after_elements")

    def _clear_truss_scratch(self) -> None:
        """Zero the force vector and matrix OpenSees' ``truss`` shares between 3D and 2D ndf 3.

        ``Truss`` keeps one class-wide vector and matrix per DOF count, and a 2D
        truss with rotations writes only their translation rows, so whatever
        the last 3D truss with three DOFs left in the rotation rows came back
        as a moment: in the reactions, and as a load and a stiffness at a joint
        free to rotate. One step of a 3D bar along X writes every entry, the Z
        rows as zero.
        """
        ops = self._ops
        ops.wipe()
        ops.model("basic", "-ndm", 3, "-ndf", 3)
        ops.node(1, 0.0, 0.0, 0.0)
        ops.node(2, 1.0, 0.0, 0.0)
        ops.fix(1, 1, 1, 1)
        ops.fix(2, 0, 1, 1)
        ops.uniaxialMaterial("Elastic", 1, 1.0)
        ops.element("truss", 1, 1, 2, 1.0, 1)
        ops.system("BandGen")
        ops.numberer("Plain")
        ops.constraints("Plain")
        ops.integrator("LoadControl", 0.0)
        ops.algorithm("Linear")
        ops.analysis("Static")
        ops.analyze(1)

    def _run_custom_commands(self, stage: str) -> None:
        """Execute the enabled custom blocks of ``stage`` (Define → Custom OpenSees Commands)."""
        for index, block in enumerate(self.project.custom_commands):
            if not block.enabled or block.stage != stage or not block.code.strip():
                continue
            namespace = {
                "ops": self._ops,
                "project": self.project,
                "ndm": self.project.ndm,
                "ndf": self.project.ndf,
                "tag": block_tag_base(index),
            }
            try:
                exec(
                    compile(block.code, f"<custom block {block.name or block.id}>", "exec"),
                    namespace,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Custom command block {block.name or block.id!r} ({stage}) failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

    def run(self, case: Any, results_dir: Path | None = None) -> Any:
        """Build the model and run the requested analysis case.

        Returns:
            :class:`StaticResults` / :class:`ModalResults` / :class:`TransientResults`
            depending on case type.
        """
        with perf.span(f"analysis.{type(case).__name__}"):
            return self._run(case, results_dir)

    def _run(self, case: Any, results_dir: Path | None = None) -> Any:
        perf.gauge("analysis.nodes", len(self.project.nodes))
        perf.gauge("analysis.elements", len(self.project.elements))
        with perf.span("analysis.checks"):
            self.project.validate_case_references(case)
            self._check_ground_motion_records(case)
            self._check_temperature_loads(case)
        with perf.span("analysis.build"):
            self.build()
        with perf.span("analysis.dof_coverage"):
            self._check_dof_coverage()
        if isinstance(case, StaticCase):
            with perf.span("analysis.static"):
                return self._run_static(case)
        if isinstance(case, ModalCase):
            with perf.span("analysis.modal"):
                return self._run_modal(case)
        if isinstance(case, PushoverCase):
            with perf.span("analysis.pushover"):
                return self._run_pushover(case)
        if isinstance(case, ResponseSpectrumCase):
            with perf.span("analysis.response_spectrum"):
                return self._run_response_spectrum(case)
        if isinstance(case, InfluenceLineCase):
            with perf.span("analysis.influence_line"):
                return self._run_influence_line(case)
        if isinstance(case, TransientCase):
            target = results_dir or Path(tempfile.mkdtemp(prefix="osstudio_"))
            with perf.span("analysis.transient"):
                return self._run_transient(case, target)
        raise TypeError(f"Unsupported analysis case type: {type(case).__name__}")

    def _check_temperature_loads(self, case: Any) -> None:
        """Temperature loads run in static cases only (their end-force correction)."""
        if isinstance(case, StaticCase):
            return
        ids = set(getattr(case, "pattern_ids", []) or [])
        for preload_id in getattr(case, "preload_case_ids", []) or []:
            preload = next((c for c in self.project.analyses if c.id == preload_id), None)
            ids.update(getattr(preload, "pattern_ids", []) or [])
        heated = [
            p.name or str(p.id)
            for p in self.project.load_patterns
            if p.id in ids and getattr(p, "temperature_loads", None)
        ]
        if heated:
            raise ValueError(
                f"Pattern(s) {', '.join(heated)} carry temperature loads, which run in static "
                "cases only."
            )

    def _check_ground_motion_records(self, case: Any) -> None:
        """Fail fast when the case uses a flagged ground-motion record.

        Collects the case's own patterns plus those of any preload cases
        and delegates to ``Project.check_ground_motion_records``, which
        raises a message naming each unusable record and its path.
        """
        pattern_ids = list(getattr(case, "pattern_ids", []))
        for preload_id in getattr(case, "preload_case_ids", []):
            preload = next((c for c in self.project.analyses if c.id == preload_id), None)
            if preload is not None:
                pattern_ids.extend(getattr(preload, "pattern_ids", []))
        self.project.check_ground_motion_records(pattern_ids)

    # ─────────────────────── nodes / fixes / mass ───────────────────────
    def _emit_node(self, node: Any) -> None:
        self._ops.node(node.id, *to_solver_coords(node.coords, self.project.ndm))

    def _solver_dofs(self, full: Any) -> list[float]:
        """A global 6-component load as the values of OpenSees' DOFs (core.plane)."""
        return [float(full[i]) * s for i, s in zip(self._dof_idx, self._dof_sign, strict=True)]

    def _emit_fix(self, node: Any, extra: set[int] | None = None) -> None:
        extra = extra or set()
        flags = tuple(int(node.restraint[i] or i in extra) for i in self._dof_idx)
        self._ops.fix(node.id, *flags)

    def _emit_mass(self, node: Any) -> None:
        # ``build`` fills the effective mass map (nodal mass plus mass source);
        # a direct emitter call in the dialogs' tests has no build and still
        # needs the node's own mass.
        mass = self._node_mass.get(node.id)
        if mass is None:
            mass = np.asarray(node.mass, dtype=float)
        m = tuple(float(mass[i]) for i in self._dof_idx)
        self._ops.mass(node.id, *m)

    def _constraints_handler(self, case: Any) -> str:
        """The case's constraint handler, Transformation where Plain cannot work.

        ``Plain`` only enforces constraints whose matrix is the identity
        (``equalDOF``); it drops a rigid diaphragm or a ``rigidLink`` with a
        warning and then solves a singular system without reporting failure.
        A model with a diaphragm, a rigid link of its own, or a frame end
        offset hung off its joint by ``rigidLink beam`` runs with
        ``Transformation`` instead.
        """
        needs = bool(self.project.diaphragms or self.project.rigid_links)
        needs = needs or self._imposes_displacement(case)
        if case.constraints == "Plain" and (needs or self._frame_plan.needs_transformation):
            return "Transformation"
        return str(case.constraints)

    def _imposes_displacement(self, case: Any) -> bool:
        """Whether ``case`` (or a preload it runs) has a pattern with imposed displacements."""
        ids = set(getattr(case, "pattern_ids", []) or [])
        for preload_id in getattr(case, "preload_case_ids", []) or []:
            preload = next((c for c in self.project.analyses if c.id == preload_id), None)
            ids.update(getattr(preload, "pattern_ids", []) or [])
        return any(
            getattr(p, "imposed_displacements", None)
            for p in self.project.load_patterns
            if p.id in ids
        )

    def _emit_mp_constraint(self, mp: Any) -> None:
        self._ops.equalDOF(mp.retained_node, mp.constrained_node, *mp.dofs)

    # ─────────────────────── materials ───────────────────────
    def _emit_material(self, mat: Any) -> None:
        """Hand the material to its emitter (see ``services/material_emitters.py``).

        A gidopensees catalog material goes through ``catalog_emitters``; a
        type with no emitter raises rather than emitting a guessed command.
        """
        if isinstance(mat, CatalogMaterial):
            emit_catalog_material(mat, self._ops)
            return
        emit_material(mat, self._ops)

    # ─────────────────────── sections ───────────────────────
    def _emit_friction_model(self, fm: Any) -> None:
        """``frictionModel`` in the live OpenSeesPy 3.8.0 argument order."""
        ops = self._ops
        match fm:
            case CoulombFriction():
                ops.frictionModel("Coulomb", fm.id, fm.mu)
            case VelDependentFriction():
                ops.frictionModel("VelDependent", fm.id, fm.mu_slow, fm.mu_fast, fm.trans_rate)
            case VelNormalFrcDepFriction():
                ops.frictionModel(
                    "VelNormalFrcDep",
                    fm.id,
                    fm.a_slow,
                    fm.n_slow,
                    fm.a_fast,
                    fm.n_fast,
                    fm.alpha0,
                    fm.alpha1,
                    fm.alpha2,
                    fm.max_mu_fact,
                )
            case _:
                raise NotImplementedError(f"Friction model type not supported: {fm.type}")

    def _emit_section(self, sec: Any) -> None:
        ops = self._ops
        if isinstance(sec, NonprismaticSection):
            # A library template. Members that use it are materialised as
            # ordinary elastic elements before the script is built.
            return
        if isinstance(sec, ElasticMembranePlateSection):
            self._emit_plate_section(sec)
            return
        if isinstance(sec, LayeredShellSection):
            layers = [v for layer in sec.layers for v in (layer.material_id, layer.thickness)]
            ops.section("LayeredShell", sec.id, len(sec.layers), *layers)
            return
        if isinstance(sec, PlateFiberSection):
            ops.section("PlateFiber", sec.id, sec.material_id, sec.h)
            return
        match sec:
            case ElasticSection():
                if self.project.ndm == 2:
                    ops.section("Elastic", sec.id, sec.E, sec.A, sec.Iz)
                else:
                    if sec.Iy is None or sec.G is None or sec.J is None:
                        raise ValueError(f"ElasticSection {sec.id} needs Iy, G, J for 3D models.")
                    ops.section("Elastic", sec.id, sec.E, sec.A, sec.Iz, sec.Iy, sec.G, sec.J)
            case FiberSection():
                if sec.GJ is not None:
                    ops.section("Fiber", sec.id, "-GJ", sec.GJ)
                elif self.project.ndm == 3:
                    torsion_mat = self._fiber_torsion_mat.get(sec.id)
                    if torsion_mat is not None:
                        # FiberSection3d requires torsion. The SectionAggregator
                        # wrapping this section will override T — use the same
                        # material so the intent is transparent.
                        ops.section("Fiber", sec.id, "-torsion", torsion_mat)
                    else:
                        raise ValueError(
                            f"FiberSection {sec.id!r} is used in a 3D model but has no "
                            "torsion defined. Either set GJ on the section or wrap it in "
                            "a SectionAggregator with a T DOF pairing."
                        )
                else:
                    ops.section("Fiber", sec.id)
                # Emit patches: rectangular / circular.
                for patch in sec.patches:
                    if patch.kind == "rect":
                        ops.patch(
                            "rect",
                            patch.material_id,
                            patch.n_fib_y,
                            patch.n_fib_z,
                            patch.y_i,
                            patch.z_i,
                            patch.y_j,
                            patch.z_j,
                        )
                    elif patch.kind == "circ":
                        ops.patch(
                            "circ",
                            patch.material_id,
                            patch.n_fib_circ,
                            patch.n_fib_rad,
                            patch.y_center,
                            patch.z_center,
                            patch.r_inner,
                            patch.r_outer,
                            patch.start_angle,
                            patch.end_angle,
                        )
                # Emit layers: straight.
                for layer in sec.layers:
                    if layer.kind == "straight":
                        ops.layer(
                            "straight",
                            layer.material_id,
                            layer.n_bars,
                            layer.bar_area,
                            layer.y_start,
                            layer.z_start,
                            layer.y_end,
                            layer.z_end,
                        )
                # Emit individual fibres (legacy / custom).
                for fb in sec.fibres:
                    ops.fiber(fb.y, fb.z, fb.area, fb.material_id)
            case SectionAggregator():
                # section Aggregator $secTag $matTag1 $dof1 ... <-section $baseSec>
                args: list[Any] = [sec.id]
                for p in sec.pairings:
                    args.extend([p.material_id, p.dof])
                if sec.section_id is not None:
                    args.extend(["-section", sec.section_id])
                ops.section("Aggregator", *args)
            case _:
                raise NotImplementedError(f"Section type not yet handled: {type(sec).__name__}")

    # ─────────────────────── geomTransf ───────────────────────
    def _allocate_and_emit_geom_transfs(self) -> None:
        """One transformation tag per (transf_type, vecxz) combination used.

        For 3D frame elements, ``vecxz`` must be a vector in the local
        x-z plane that is NOT parallel to the local x-axis (the element
        axis). We compute the element axis from the node coordinates,
        then pick a ``vecxz`` orthogonal to it:

        - element axis nearly parallel to global Z (vertical column) →
          vecxz = (1, 0, 0)
        - everything else (horizontal beam, sloped brace) → vecxz = (0, 0, 1)

        Each frame element gets a tag in ``_element_geom_transf_tag`` so
        :meth:`_emit_element` can look up the right one.
        """
        import numpy as np

        frame_types = (
            ElasticBeamColumn,
            ForceBeamColumn,
            DispBeamColumn,
            BeamWithHingesElement,
        )
        node_coords = {n.id: np.array(n.coords, dtype=float) for n in self.project.nodes}

        # Allocate (transf_type, vecxz_tuple, joint offsets) → tag, lazily.
        combo_to_tag: dict[tuple[Any, ...], int] = {}
        self._element_geom_transf_tag = {}
        next_tag = 1

        for el in self.project.elements:
            if not isinstance(el, frame_types):
                continue
            # End offsets and insertion points: ``-jntOffset`` (services/frame_members.py).
            member = self._frame_plan.members.get(el.id)
            offsets = member.joint_offset if member is not None else ()
            tail: list[Any] = ["-jntOffset", *offsets] if offsets else []
            if self.project.ndm == 2:
                key = (el.geom_transf, (0.0, 0.0, 0.0), offsets)  # vecxz unused in 2D
                if key not in combo_to_tag:
                    combo_to_tag[key] = next_tag
                    self._ops.geomTransf(el.geom_transf, next_tag, *tail)
                    next_tag += 1
                self._element_geom_transf_tag[el.id] = combo_to_tag[key]
                continue

            # 3D: pick vecxz orthogonal to the element axis.
            vecxz = frame_vecxz(node_coords[el.nodes[0]], node_coords[el.nodes[1]])

            key = (el.geom_transf, vecxz, offsets)
            if key not in combo_to_tag:
                combo_to_tag[key] = next_tag
                self._ops.geomTransf(el.geom_transf, next_tag, *vecxz, *tail)
                next_tag += 1
            self._element_geom_transf_tag[el.id] = combo_to_tag[key]

        # Backward-compat for tests that read _geom_transf_tags.
        self._geom_transf_tags = {k[0]: v for k, v in combo_to_tag.items()}

    # ─────────────────────── elements ───────────────────────
    def _bearing_orient(self, el: Any) -> tuple[float, ...]:
        """``(x1, x2, x3, y1, y2, y3)`` for an elastomeric or sliding bearing.

        The user's ``orient`` wins. Otherwise x is the element axis (node i
        to node j) or, for coincident nodes, the vertical (global Z; OpenSees'
        y of a 2D model, see core.plane); y is the shear direction, global X unless the axis
        is horizontal, then the horizontal perpendicular to the axis.
        OpenSees 3.8 terminates the process when a zero-length bearing has
        no -orient, so the six values are always written.
        """
        if el.orient is not None:
            ndm_o = self.project.ndm
            return (
                *to_solver_vector3(el.orient[:3], ndm_o),
                *to_solver_vector3(el.orient[3:6], ndm_o),
            )
        ndm = self.project.ndm
        # Worked out in OpenSees' own frame: a 2D model's (X, Z) are its (x, y).
        pi = np.asarray(to_solver_vector3(self.project.node(el.nodes[0]).coords, ndm), dtype=float)
        pj = np.asarray(to_solver_vector3(self.project.node(el.nodes[1]).coords, ndm), dtype=float)
        if ndm == 2:
            pi[2] = pj[2] = 0.0
        axis = pj - pi
        length = float(np.linalg.norm(axis))
        up = np.array([0.0, 1.0, 0.0]) if ndm == 2 else np.array([0.0, 0.0, 1.0])
        x = axis / length if length > 1e-12 else up
        y = np.cross(up, x) if ndm == 3 else np.array([x[1], -x[0], 0.0])
        if float(np.linalg.norm(y)) < 1e-9:
            y = np.array([1.0, 0.0, 0.0])
        y = y / float(np.linalg.norm(y))
        return (*(float(v) for v in x), *(float(v) for v in y))

    def _bearing_args(self, el: Any) -> list[Any]:
        """Argument list of ``ops.element`` for a bearing element.

        Matches the live OpenSeesPy 3.8.0 signatures::

            elastomericBearingPlasticity tag i j kInit qd alpha1 alpha2 mu
                -P p -Mz mz            (2D)
                -P p -T t -My my -Mz mz  (3D)
                -orient x1 x2 x3 y1 y2 y3 <-shearDist s> <-doRayleigh> <-mass m>
            elastomericBearingBoucWen tag i j kInit qd alpha1 alpha2 mu eta beta gamma
                ... same trailing arguments
            flatSliderBearing tag i j frnTag kInit
                ... same materials and trailing arguments, then <-iter maxIter tol>
            singleFPBearing tag i j frnTag Reff kInit
                ... same materials and trailing arguments, then <-iter maxIter tol>
        """
        args: list[Any]
        if isinstance(el, SLIDING_BEARING_CLASSES):
            if el.type == "SingleFPBearing":
                args = ["singleFPBearing", el.id, *el.nodes, el.friction_model_id, el.r_eff]
            else:
                args = ["flatSliderBearing", el.id, *el.nodes, el.friction_model_id]
            args.append(el.k_init)
        else:
            name = (
                "elastomericBearingBoucWen"
                if el.type == "ElastomericBearingBoucWen"
                else "elastomericBearingPlasticity"
            )
            args = [name, el.id, *el.nodes, el.k_init, el.qd, el.alpha1, el.alpha2, el.mu]
            if el.type == "ElastomericBearingBoucWen":
                args += [el.eta, el.beta, el.gamma]
        if self.project.ndm == 3:
            if el.t_material_id is None or el.my_material_id is None:
                raise ValueError(
                    f"Bearing {el.id} needs T and My materials in a 3D model "
                    "(t_material_id, my_material_id)."
                )
            args += [
                "-P",
                el.p_material_id,
                "-T",
                el.t_material_id,
                "-My",
                el.my_material_id,
                "-Mz",
                el.mz_material_id,
            ]
        else:
            args += ["-P", el.p_material_id, "-Mz", el.mz_material_id]
        if os.environ.get(SKIP_BEARING_ORIENT_ENV, "").strip() != "1":
            args += ["-orient", *self._bearing_orient(el)]
        if el.shear_dist != 0.5:
            args += ["-shearDist", el.shear_dist]
        if el.do_rayleigh:
            args.append("-doRayleigh")
        if el.mass > 0.0:
            args += ["-mass", el.mass]
        if isinstance(el, SLIDING_BEARING_CLASSES) and (el.max_iter != 25 or el.tol != 1e-12):
            args += ["-iter", el.max_iter, el.tol]
        return args

    def _emit_plate_section(self, sec: Any) -> None:
        """``section ElasticMembranePlateSection tag E nu h rho``.

        The section ShellMITC4 takes. OpenSees defines it by its own (E, nu, h,
        rho), so it never references an nDMaterial.
        """
        self._ops.section("ElasticMembranePlateSection", sec.id, sec.E, sec.nu, sec.h, sec.rho)

    def _frame_nodes(self, el: Any) -> tuple[int, int]:
        """The node tags a frame's ``element`` command uses: a released end's hidden node."""
        member = self._frame_plan.members.get(el.id)
        return member.nodes if member is not None else (el.nodes[0], el.nodes[1])

    def _frame_section(self, el: Any) -> int:
        """The section a frame uses: a derived section when its stiffness is modified."""
        member = self._frame_plan.members.get(el.id)
        if member is not None and member.section_id is not None:
            return member.section_id
        return int(el.section_id)

    def _emit_element(self, el: Any) -> None:
        ops = self._ops
        match el:
            case TrussElement():
                ops.element("truss", el.id, *el.nodes, el.area, el.material_id, "-rho", el.rho)
            case CorotTrussElement():
                ops.element("corotTruss", el.id, *el.nodes, el.area, el.material_id, "-rho", el.rho)
            case ElasticBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                member = self._frame_plan.members.get(el.id)
                rho = member.rho if member is not None and member.rho is not None else el.rho
                ebc_args: list[Any] = [self._frame_section(el), tag, "-mass", rho]
                if el.consistent_mass:
                    ebc_args.append("-cMass")
                if member is not None and member.timoshenko is not None:
                    # Shear areas on the section: a Timoshenko beam (no sections, no -release).
                    t_args: list[Any] = [*member.timoshenko, tag, "-mass", rho]
                    if el.consistent_mass:
                        t_args.append("-cMass")
                    ops.element("ElasticTimoshenkoBeam", el.id, *self._frame_nodes(el), *t_args)
                    return
                # A release at a constrained joint is condensed in the element.
                if member is not None:
                    ebc_args.extend(member.release_args)
                ops.element(
                    "elasticBeamColumn",
                    el.id,
                    *self._frame_nodes(el),
                    *ebc_args,
                )
            case ForceBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.beamIntegration(
                    el.integration, el.id, self._frame_section(el), el.integration_points
                )
                ops.element(
                    "forceBeamColumn",
                    el.id,
                    *self._frame_nodes(el),
                    tag,
                    el.id,
                    "-iter",
                    el.max_iter,
                    el.tolerance,
                )
            case DispBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.beamIntegration(
                    el.integration, el.id, self._frame_section(el), el.integration_points
                )
                ops.element("dispBeamColumn", el.id, *self._frame_nodes(el), tag, el.id)
            case ZeroLengthElement():
                zl_args: list[Any] = [
                    "zeroLength",
                    el.id,
                    *el.nodes,
                    "-mat",
                    *el.material_ids,
                    "-dir",
                    *el.dofs,
                ]
                # ``-doRayleigh 1`` only when requested (default off, matching
                # OpenSees' zeroLength default) — so an isolator can opt its
                # stiffness into a Kinit-proportional Rayleigh damping matrix.
                if el.do_rayleigh:
                    zl_args += ["-doRayleigh", 1]
                ops.element(*zl_args)
            case el if isinstance(el, BEARING_CLASSES):
                ops.element(*self._bearing_args(el))
            case TwoNodeLinkElement():
                ops.element("twoNodeLink", el.id, *el.nodes, *el.opensees_args(self.project.ndm))
            case TripleFrictionPendulumElement():
                ops.element("TripleFrictionPendulum", el.id, *el.nodes, *el.opensees_args())
            case MVLEMElement():
                ops.element("MVLEM", el.id, *el.opensees_args())
            case ZeroLengthSectionElement():
                # element zeroLengthSection $eleTag $iNode $jNode $secTag
                ops.element(
                    "zeroLengthSection",
                    el.id,
                    *el.nodes,
                    el.section_id,
                )
            case ShellMITC4Element():
                # element ShellMITC4 eleTag n1 n2 n3 n4 secTag
                ops.element("ShellMITC4", el.id, *el.nodes, el.section_id)
            case QuadElement() if True:
                # element quad         eleTag n1 n2 n3 n4 thk type matTag <pressure rho b1 b2>
                # element bbarQuad     eleTag n1 n2 n3 n4 thk matTag
                # element enhancedQuad eleTag n1 n2 n3 n4 thk type matTag
                if el.variant == "quad":
                    ops.element(
                        "quad",
                        el.id,
                        *el.nodes,
                        el.thickness,
                        el.behaviour,
                        el.material_id,
                        el.pressure,
                        el.rho,
                        el.b1,
                        el.b2,
                    )
                elif el.variant == "bbarQuad":
                    ops.element(
                        "bbarQuad",
                        el.id,
                        *el.nodes,
                        el.thickness,
                        el.material_id,
                    )
                else:  # enhancedQuad
                    ops.element(
                        "enhancedQuad",
                        el.id,
                        *el.nodes,
                        el.thickness,
                        el.behaviour,
                        el.material_id,
                    )
            case BeamWithHingesElement():
                tag = self._element_geom_transf_tag[el.id]
                # OpenSees 3D signature:
                #   element beamWithHinges id ni nj secI lpI secJ lpJ E A Iz Iy G J transfTag
                # 2D signature drops Iy, G, J:
                #   element beamWithHinges id ni nj secI lpI secJ lpJ E A Iz transfTag
                member = self._frame_plan.members.get(el.id)
                inline = member.inline if member is not None else {}
                args = [
                    el.id,
                    *self._frame_nodes(el),
                    el.section_i_id,
                    el.lp_i,
                    el.section_j_id,
                    el.lp_j,
                    el.E,
                    inline.get("A", el.A),
                    inline.get("Iz", el.Iz),
                ]
                if self.project.ndm == 3:
                    if el.Iy is None or el.G is None or el.J is None:
                        raise ValueError(
                            f"BeamWithHinges {el.id} needs Iy, G, J in 3D models.",
                        )
                    args.extend([inline.get("Iy", el.Iy), el.G, inline.get("J", el.J)])
                args.append(tag)
                ops.element("beamWithHinges", *args)
            case _:
                raise NotImplementedError(f"Element type not yet handled: {type(el).__name__}")

    # ─────────────────────── time series + patterns ───────────────────────
    def _emit_time_series(self, ts: Any) -> None:
        ops = self._ops
        match ts:
            case LinearTimeSeries():
                ops.timeSeries("Linear", ts.id, "-factor", ts.factor)
            case ConstantTimeSeries():
                ops.timeSeries("Constant", ts.id, "-factor", ts.factor)
            case PathTimeSeries():
                tail: list[Any] = ["-useLast"] if ts.use_last else []
                if ts.dt is not None:
                    ops.timeSeries(
                        "Path",
                        ts.id,
                        "-dt",
                        ts.dt,
                        "-values",
                        *ts.values,
                        "-factor",
                        ts.factor,
                        *tail,
                    )
                elif ts.times is not None:
                    ops.timeSeries(
                        "Path",
                        ts.id,
                        "-time",
                        *ts.times,
                        "-values",
                        *ts.values,
                        "-factor",
                        ts.factor,
                        *tail,
                    )
                else:
                    raise ValueError(
                        f"PathTimeSeries {ts.id}: either ``dt`` or ``times`` is required."
                    )
            case TrigTimeSeries():
                ops.timeSeries(
                    "Trig",
                    ts.id,
                    ts.t_start,
                    ts.t_end,
                    ts.period,
                    "-factor",
                    ts.factor,
                    "-shift",
                    ts.shift,
                    "-zeroShift",
                    ts.zero_shift,
                )
            case TriangleTimeSeries():
                ops.timeSeries(
                    "Triangle",
                    ts.id,
                    ts.t_start,
                    ts.t_end,
                    ts.period,
                    "-factor",
                    ts.factor,
                    "-shift",
                    ts.shift,
                    "-zeroShift",
                    ts.zero_shift,
                )
            case RectangularTimeSeries():
                ops.timeSeries("Rectangular", ts.id, ts.t_start, ts.t_end, "-factor", ts.factor)
            case PulseTimeSeries():
                ops.timeSeries(
                    "Pulse",
                    ts.id,
                    ts.t_start,
                    ts.t_end,
                    ts.period,
                    "-width",
                    ts.width,
                    "-shift",
                    ts.shift,
                    "-factor",
                    ts.factor,
                    "-zeroShift",
                    ts.zero_shift,
                )
            case _:
                raise NotImplementedError(f"TimeSeries type not yet handled: {type(ts).__name__}")

    def _emit_pattern(self, pat: Any) -> None:
        ops = self._ops
        match pat:
            case PlainLoadPattern():
                ops.pattern("Plain", pat.id, pat.time_series_id)
                for nl in pat.nodal_loads:
                    ops.load(nl.node_id, *self._solver_dofs(nl.forces))
                # Temperature: minus the fixed-end forces at the member's joints;
                # the static run adds them back to the member's end forces.
                for thermal in pat.temperature_loads:
                    node_i, load_i, node_j, load_j = equivalent_nodal_loads(self.project, thermal)
                    ops.load(node_i, *self._solver_dofs(load_i))
                    ops.load(node_j, *self._solver_dofs(load_j))
                # Shells and trusses: their self weight as nodal forces (translations only).
                for node_id, force in nodal_self_weight_loads(
                    self.project, pat.self_weight
                ).items():
                    full = (*(float(f) for f in force), 0.0, 0.0, 0.0)
                    ops.load(node_id, *self._solver_dofs(full))
                # Pressure on shells: consistent nodal forces (core.area_loads).
                for node_id, force in surface_nodal_loads(self.project, pat.surface_loads).items():
                    full = (*(float(f) for f in force), 0.0, 0.0, 0.0)
                    ops.load(node_id, *self._solver_dofs(full))
                # Imposed displacements: the support's own (homogeneous) sp goes,
                # the pattern's takes its place. Plain cannot enforce a nonzero sp,
                # so such a case runs with Transformation (_constraints_handler).
                for imposed in pat.imposed_displacements:
                    node = self.project.node(imposed.node_id)
                    slot = self._dof_idx[imposed.dof - 1]
                    if node.restraint[slot]:
                        ops.remove("sp", imposed.node_id, imposed.dof)
                    ops.sp(
                        imposed.node_id,
                        imposed.dof,
                        imposed.value * float(self._dof_sign[imposed.dof - 1]),
                    )
                # A member with rigid end zones takes its loads through the
                # split below; every other member exactly as before.
                rigid = {
                    eid
                    for eid, member in self._frame_plan.members.items()
                    if member.layout is not None and member.layout.has_rigid_zones
                }
                uniform = [*pat.element_loads, *self_weight_loads(self.project, pat.self_weight)]
                for el in uniform:
                    # eleLoad -ele N -type -beamUniform wy wz wx
                    # (the pattern's self weight is a uniform load per frame).
                    # 2D: only (wy, wx) are emitted (wz drops).
                    # 3D: (wy, wz, wx).
                    if el.element_id in rigid:
                        continue
                    if self.project.ndm == 2:
                        ops.eleLoad("-ele", el.element_id, "-type", "-beamUniform", el.wy, el.wx)
                    else:
                        ops.eleLoad(
                            "-ele", el.element_id, "-type", "-beamUniform", el.wy, el.wz, el.wx
                        )
                for pl in pat.point_loads:
                    # eleLoad -ele N -type -beamPoint Py <Pz> xL Px
                    # 2D: (Py, xL, Px); 3D: (Py, Pz, xL, Px).
                    if pl.element_id in rigid:
                        continue
                    self._require_beamlike_loads(pl.element_id)
                    if self.project.ndm == 2:
                        ops.eleLoad(
                            "-ele", pl.element_id, "-type", "-beamPoint", pl.py, pl.x, pl.px
                        )
                    else:
                        ops.eleLoad(
                            "-ele", pl.element_id, "-type", "-beamPoint", pl.py, pl.pz, pl.x, pl.px
                        )
                self._emit_member_loads(pat, rigid, uniform)
            case UniformExcitationPattern():
                args: list[Any] = [pat.direction, "-accel", pat.accel_series_id]
                if pat.vel_series_id is not None:
                    args.extend(["-vel", pat.vel_series_id])
                if pat.disp_series_id is not None:
                    args.extend(["-disp", pat.disp_series_id])
                if pat.factor != 1.0:
                    args.extend(["-fact", pat.factor])
                ops.pattern("UniformExcitation", pat.id, *args)
            case ImposedSupportMotionPattern():
                self._emit_imposed_support_motion(pat)
            case _:
                raise NotImplementedError(f"Pattern type not yet handled: {type(pat).__name__}")

    def _emit_member_loads(
        self, pat: PlainLoadPattern, rigid: set[int], uniform: list[Any]
    ) -> None:
        """Distributed (trapezoidal) loads, and every load of a member with rigid end zones.

        Each member's loads are split between its flexible part and its joints
        (:func:`core.frame_members.split_member_loads`). On the flexible part a
        full-length uniform load stays ``-beamUniform``. Any other linear piece
        goes to a force-based element (``forceBeamColumn``, ``beamWithHinges``)
        as the native partial/trapezoidal ``-beamUniform``, which it integrates
        at its integration points; an elastic or displacement-based element gets
        three ``-beamPoint`` loads at the Gauss points instead, which give its
        exact end forces. (OpenSees 3.8's 3D elastic element ignores the
        trapezoid's end values and ``dispBeamColumn`` drops partial loads with
        only a warning, so the native form is not an option for them.)
        """
        by_element: dict[int, tuple[list[Any], list[Any]]] = {}
        for ul in uniform:
            if ul.element_id in rigid:
                w = (ul.wx, ul.wy, ul.wz)
                by_element.setdefault(ul.element_id, ([], []))[0].append((0.0, 1.0, w, w))
        for dl in pattern_distributed_loads(self.project, pat):
            by_element.setdefault(dl.element_id, ([], []))[0].append(
                (dl.x_start, dl.x_end, dl.start(), dl.end())
            )
        for pl in pat.point_loads:
            if pl.element_id in rigid:
                by_element.setdefault(pl.element_id, ([], []))[1].append(
                    (pl.x, (pl.px, pl.py, pl.pz))
                )
        elements = {el.id: el for el in self.project.elements}
        for eid, (segments, points) in by_element.items():
            member = self._frame_plan.members.get(eid)
            if member is None or member.layout is None:
                raise ValueError(f"Element {eid} carries a frame load but is not a frame member.")
            layout = member.layout
            split = split_member_loads(layout, segments, points)
            el = elements[eid]
            for piece in split.pieces:
                self._emit_clear_piece(el, piece, layout.clear_length)
            for point in split.points:
                self._emit_beam_point(eid, point)
            for end, (force, moment) in split.joint.items():
                full = (*force, *moment)
                values = self._solver_dofs(full)
                if any(values):
                    self._ops.load(el.nodes[0] if end == "i" else el.nodes[1], *values)

    def _emit_clear_piece(self, el: Any, piece: ClearPiece, clear_length: float) -> None:
        wx_a, wy_a, wz_a = (float(v) for v in piece.w_a)
        if piece.is_uniform_full:
            if self.project.ndm == 2:
                self._ops.eleLoad("-ele", el.id, "-type", "-beamUniform", wy_a, wx_a)
            else:
                self._ops.eleLoad("-ele", el.id, "-type", "-beamUniform", wy_a, wz_a, wx_a)
            return
        if isinstance(el, (ForceBeamColumn, BeamWithHingesElement)):
            wx_b, wy_b, wz_b = (float(v) for v in piece.w_b)
            a, b = float(piece.a), float(piece.b)
            # 2D: Wya Wxa aL bL Wyb Wxb; 3D: Wya Wza Wxa aL bL Wyb Wzb Wxb.
            if self.project.ndm == 2:
                args: list[Any] = [wy_a, wx_a, a, b, wy_b, wx_b]
            else:
                args = [wy_a, wz_a, wx_a, a, b, wy_b, wz_b, wx_b]
            self._ops.eleLoad("-ele", el.id, "-type", "-beamUniform", *args)
            return
        for point in gauss_point_loads(piece, clear_length):
            self._emit_beam_point(el.id, point)

    def _require_beamlike_loads(self, element_id: int) -> None:
        """OpenSees 3.8's ``ElasticTimoshenkoBeam`` takes only full-length uniform loads."""
        member = self._frame_plan.members.get(element_id)
        if member is not None and member.timoshenko is not None:
            raise ValueError(
                f"Element {element_id} has a section with shear areas (a Timoshenko beam), "
                "which OpenSees 3.8 loads only with full-length uniform loads: point, partial "
                "and trapezoidal loads are refused. Remove the shear areas from the section "
                "or load the member with a uniform load."
            )

    def _emit_beam_point(self, element_id: int, point: ClearPoint) -> None:
        self._require_beamlike_loads(element_id)
        px, py, pz = (float(v) for v in point.p)
        x = float(point.x)
        if self.project.ndm == 2:
            self._ops.eleLoad("-ele", element_id, "-type", "-beamPoint", py, x, px)
        else:
            self._ops.eleLoad("-ele", element_id, "-type", "-beamPoint", py, pz, x, px)

    def _emit_imposed_support_motion(self, pat: ImposedSupportMotionPattern) -> None:
        """``pattern MultipleSupport`` + shared ``groundMotion`` + per-node ``imposedMotion``.

        The support nodes are modelled FIXED in the driven DOF, so static
        preloads and modal cases see an ordinary grounded support. The fix is
        swapped for the imposed motion here — at pattern-emission time, which
        for a transient case is AFTER the preload sequence — i.e. the ground is
        at rest until the transient starts (the disp record begins at 0).

        ``ImposedMotionSP`` enforces displacement AND velocity at the node.
        The velocity is what carries the support motion into the
        stiffness-proportional (Rayleigh betaKinit) damping forces of
        ``-doRayleigh`` elements, and OpenSees's internal differentiation of a
        ``-disp``-only ground motion is unreliable — so the runner derives the
        velocity companion from the displacement record by central differences
        and hands both series to the ground motion explicitly.
        """
        ops = self._ops
        if pat.direction > self.project.ndf:
            raise ValueError(
                f"ImposedSupportMotion {pat.id}: direction {pat.direction} "
                f"exceeds ndf={self.project.ndf}."
            )
        slot = self._dof_idx[pat.direction - 1]
        nodes_by_id = {n.id: n for n in self.project.nodes}
        for nid in pat.node_ids:
            if not nodes_by_id[nid].restraint[slot]:
                raise ValueError(
                    f"ImposedSupportMotion {pat.id}: node {nid} must be "
                    f"restrained in direction {pat.direction} — the imposed "
                    f"motion replaces that fix at transient start."
                )
        ts = next(t for t in self.project.time_series if t.id == pat.disp_series_id)
        if not isinstance(ts, PathTimeSeries) or ts.dt is None:
            raise ValueError(
                f"ImposedSupportMotion {pat.id}: disp_series_id must reference "
                f"a PathTimeSeries with uniform ``dt``."
            )
        vel_tag = _IMPOSED_VEL_TS_OFFSET + pat.id
        if any(t.id == vel_tag for t in self.project.time_series):
            raise ValueError(
                f"ImposedSupportMotion {pat.id}: derived velocity-series tag "
                f"{vel_tag} collides with an existing time series."
            )
        vel = np.gradient(np.asarray(ts.values, dtype=float), ts.dt)
        ops.timeSeries(
            "Path",
            vel_tag,
            "-dt",
            ts.dt,
            "-values",
            *vel.tolist(),
            "-factor",
            ts.factor,
        )
        for nid in pat.node_ids:
            ops.remove("sp", nid, pat.direction)
        ops.pattern("MultipleSupport", pat.id)
        ops.groundMotion(
            pat.id,
            "Plain",
            "-disp",
            pat.disp_series_id,
            "-vel",
            vel_tag,
            "-fact",
            pat.factor,
        )
        for nid in pat.node_ids:
            ops.imposedMotion(nid, pat.direction, pat.id)

    # ─────────────────────── analysis runners ───────────────────────
    def _emit_patterns_for_case(self, pattern_ids: list[int]) -> None:
        # Time series for the patterns we are about to emit.
        used_ts: set[int] = set()
        for pid in pattern_ids:
            pat = next(p for p in self.project.load_patterns if p.id == pid)
            for ts_id in (
                getattr(pat, "time_series_id", None),
                getattr(pat, "accel_series_id", None),
                getattr(pat, "vel_series_id", None),
                getattr(pat, "disp_series_id", None),
            ):
                if ts_id is not None:
                    used_ts.add(ts_id)
        for ts in self.project.time_series:
            if ts.id in used_ts:
                self._emit_time_series(ts)
        for pid in pattern_ids:
            pat = next(p for p in self.project.load_patterns if p.id == pid)
            self._emit_pattern(pat)

    def _run_preload_sequence(self, preload_ids: list[int], parent_case_id: int) -> None:
        """Run a list of StaticCase preloads, then lock load + reset time.

        Shared by :meth:`_run_transient` and :meth:`_run_pushover`. After
        all preload cases finish, ``ops.loadConst -time 0.0`` freezes the
        applied load as a baseline (any Linear time series attached to
        subsequent patterns won't re-ramp it) and rewinds pseudo-time so
        the continuation case begins at t=0. ``wipeAnalysis`` clears the
        static analysis objects so the caller can install its own
        integrator / algorithm.
        """
        ops = self._ops
        if not preload_ids:
            return
        # Every preload pattern keeps ramping through the later preload cases.
        applied_ids: list[int] = []
        for preload_id in preload_ids:
            preload_case = next(
                (c for c in self.project.analyses if c.id == preload_id),
                None,
            )
            if preload_case is None:
                raise ValueError(
                    f"AnalysisCase {parent_case_id}: preload_case_ids "
                    f"references missing AnalysisCase id={preload_id}."
                )
            if not isinstance(preload_case, StaticCase):
                raise TypeError(
                    f"AnalysisCase {parent_case_id}: preload_case_ids only "
                    f"supports StaticCase entries; got "
                    f"{type(preload_case).__name__}."
                )
            self._emit_patterns_for_case(preload_case.pattern_ids)
            applied_ids.extend(preload_case.pattern_ids)
            self._setup_analysis(preload_case)
            correct = self._needs_correction_solve(preload_case, applied_ids)
            for step in range(preload_case.n_steps):
                if self._analyze_static_step(preload_case, correct) != 0:
                    raise RuntimeError(
                        f"Preload StaticCase {preload_case.id} failed at "
                        f"step {step + 1}/{preload_case.n_steps}."
                    )
        ops.loadConst("-time", 0.0)
        ops.wipeAnalysis()

    #: Convergence tests that measure the force unbalance: an iterating
    #: algorithm with one of these already sees a hidden element load.
    _FORCE_TESTS = frozenset({"NormUnbalance"})
    #: Tests relative to the first iteration, which is zero in such a step.
    _RELATIVE_TESTS = frozenset({"RelativeNormDispIncr", "RelativeEnergyIncr"})

    def _needs_correction_solve(self, case: StaticCase, pattern_ids: list[int]) -> bool:
        """Whether each step must be followed by a zero-increment correction solve.

        A force-based frame (``forceBeamColumn``, ``beamWithHinges``) only takes
        an element load (``-beamUniform``, ``-beamPoint``) into its resisting
        force at its next state determination, which comes after the solve.
        The first solve of a step therefore sees no unbalance from it and moves
        nothing: Linear stops there, and an iterating algorithm whose test
        measures the displacement or energy increment (NormDispIncr, EnergyIncr)
        takes that zero increment as convergence. Either way the step lags one
        load increment: a simply supported beam reports the fixed-end reactions
        and no rotation after the first step. A force test (NormUnbalance) sees
        the unbalance after the update and iterates on it, so Newton with
        NormUnbalance is already right. The elastic and displacement-based
        frames put the load straight into their resisting force.

        Raises ``ValueError`` for a test relative to the first iteration with
        more than one step: from the second step on that first increment is
        exactly zero, so the relative reduction can never be met.
        """
        if case.integrator != "LoadControl":
            return False
        if case.algorithm != "Linear" and case.test in self._FORCE_TESTS:
            return False
        force_based = {
            el.id
            for el in self.project.elements
            if isinstance(el, (ForceBeamColumn, BeamWithHingesElement))
        }
        if not force_based:
            return False
        ids = set(pattern_ids)
        for pat in self.project.load_patterns:
            if pat.id not in ids:
                continue
            loads = [
                *getattr(pat, "element_loads", ()),
                *getattr(pat, "point_loads", ()),
                *pattern_distributed_loads(self.project, pat),
                *self_weight_loads(self.project, getattr(pat, "self_weight", 0.0)),
            ]
            if any(load.element_id in force_based for load in loads):
                break
        else:
            return False
        if case.algorithm != "Linear" and case.test in self._RELATIVE_TESTS and case.n_steps > 1:
            raise ValueError(
                f"StaticCase {case.id}: the {case.test} test cannot converge over "
                f"{case.n_steps} steps here: a force-based frame carries an element "
                "load, so the first iteration of every step after the first moves "
                "nothing. Use NormDispIncr, EnergyIncr or NormUnbalance."
            )
        return True

    def _analyze_static_step(self, case: StaticCase, correct: bool) -> int:
        """One static step; with ``correct``, a second solve at the same load.

        The second solve runs the case's own algorithm and test with a zero
        load increment, so it moves neither the load factor nor pseudo-time and
        only removes the unbalance the force-based elements report once updated
        (see :meth:`_needs_correction_solve`). For Linear and linear sections
        that is the exact answer, with no convergence tolerance involved; an
        iterating algorithm converges on it from the state the first solve
        committed (the previous displacements, with the new load inside the
        elements).
        """
        ops = self._ops
        status = ops.analyze(1)
        if status != 0 or not correct:
            return status
        ops.integrator(case.integrator, 0.0)
        status = ops.analyze(1)
        ops.integrator(case.integrator, case.load_factor_increment)
        return status

    def _constraints(self, case: Any) -> None:
        """``constraints``: the case's handler, Transformation instead of Plain when needed
        (see :meth:`_constraints_handler`)."""
        self._ops.constraints(self._constraints_handler(case))

    def _node_reactions(self, node_id: int, ndf: int) -> list[float]:
        """``nodeReaction`` of every DOF, plus what reaches the node through its hidden nodes.

        A released member end hangs off a hidden node tied to the joint by
        ``equalDOF`` (or ``rigidLink``), and OpenSees reports the force that
        crosses such a constraint at the hidden node, not at the joint. Each
        hidden node's reaction is added back, moved to the joint (plus the
        moment of its force about the joint for a face node).
        """
        ops = self._ops
        total = [ops.nodeReaction(node_id, dof) for dof in range(1, ndf + 1)]
        attached = self._frame_plan.attached.get(node_id)
        if not attached:
            return total
        ndm = self.project.ndm
        joint = np.asarray(to_solver_coords(self.project.node(node_id).coords, ndm), dtype=float)
        for extra in attached:
            r = [float(ops.nodeReaction(extra.tag, dof)) for dof in range(1, ndf + 1)]
            arm = np.asarray(extra.coords, dtype=float) - joint
            for k in range(ndm):
                total[k] += r[k]
            if ndm == 2 and ndf == 3:
                total[2] += r[2] + arm[0] * r[1] - arm[1] * r[0]
            elif ndm == 3 and ndf == 6:
                moment = np.cross(arm, r[:3])
                for k in range(3):
                    total[3 + k] += r[3 + k] + float(moment[k])
        return total

    def _setup_analysis(self, case: Any) -> None:
        ops = self._ops
        ops.system(case.system, *case.system_args)
        ops.numberer(case.numberer)
        self._constraints(case)
        ops.test(case.test, *test_args(case.test, case.tolerance, case.max_iter))
        ops.algorithm(case.algorithm, *case.algorithm_args)
        if isinstance(case, StaticCase):
            ops.integrator(case.integrator, case.load_factor_increment)
        elif isinstance(case, TransientCase):
            ops.integrator(case.integrator, *transient_integrator_args(case))
            # Apply Rayleigh damping (C = alphaM*M + betaK*K) in a SINGLE
            # ``rayleigh`` call (a second call silently replaces the first). The
            # four args are alphaM and the betaK multipliers on current-K /
            # initial-K / commit-K: ``rayleigh 0 0 betaKinit 0`` is the Kinit-
            # proportional (initial-stiffness) idiom an isolated structure uses.
            alpha = float(getattr(case, "rayleigh_alpha_m", 0.0))
            beta = float(getattr(case, "rayleigh_beta_k", 0.0))
            beta_init = float(getattr(case, "rayleigh_beta_k_init", 0.0))
            beta_comm = float(getattr(case, "rayleigh_beta_k_comm", 0.0))
            if alpha != 0.0 or beta != 0.0 or beta_init != 0.0 or beta_comm != 0.0:
                ops.rayleigh(alpha, beta, beta_init, beta_comm)
        ops.analysis("Static" if isinstance(case, StaticCase) else "Transient")

    def _check_dof_coverage(self) -> None:
        """Fail loudly if any free DOF has no element contributing to it.

        OpenSees's direct solver returns a singular-matrix *warning* but
        `analyze` still returns 0, so the runner would otherwise pass
        garbage displacements back to the user (typically the load vector
        shows up verbatim as the displacement). The most common trigger:
        a pure-truss model with ndf=3 (rotational DOFs free but no frame
        element to resist them). Instead of auto-constraining, we tell
        the user exactly what went wrong so they can set ndf correctly
        or add the missing frame element / constraint.
        """
        from opensees_studio.core import (
            BeamWithHingesElement,
            CorotTrussElement,
            DispBeamColumn,
            ElasticBeamColumn,
            ForceBeamColumn,
            TrussElement,
            ZeroLengthSectionElement,
        )

        if any(block.enabled for block in self.project.custom_commands):
            # A custom block may add the stiffness itself; the solver will say if not.
            return
        truss_types = (TrussElement, CorotTrussElement)
        frame_types = (
            ElasticBeamColumn,
            DispBeamColumn,
            ForceBeamColumn,
            BeamWithHingesElement,
        )
        # zeroLengthSection wires a full Section (P, Mz, My, T, V…) into
        # every DOF of both nodes — treat it as a frame for the coverage
        # check so Moment-Curvature models with free Rz don't get
        # rejected as singular.
        section_types = (ZeroLengthSectionElement,)

        # Per-node bitmask of DOFs with stiffness contribution from any
        # connected element. We work in canonical 6-DOF slot terms so the
        # comparison with ``_dof_idx`` is straightforward.
        active: dict[int, set[int]] = {n.id: set() for n in self.project.nodes}
        for el in self.project.elements:
            if isinstance(el, truss_types):
                contributed = {0, 1, 2}  # translations only
            elif isinstance(el, (frame_types, section_types)):
                contributed = {0, 1, 2, 3, 4, 5}
            else:
                # Unknown type: assume it covers every DOF (safe default).
                contributed = {0, 1, 2, 3, 4, 5}
            for end, nid in zip(("i", "j"), el.nodes, strict=False):
                if nid not in active:
                    continue
                # A released end leaves the joint's matching rotations unstiffened.
                released = self._frame_plan.released_dofs.get((el.id, end), set())
                slots = {self._dof_idx[dof - 1] for dof in released}
                active[nid].update(contributed - slots)
            for nid in el.nodes[2:]:
                if nid in active:
                    active[nid].update(contributed)

        # Constraints carry stiffness too: a diaphragm's retained node gets its
        # in-plane DOFs from the floor (the rest the runner fixes), a rigid link
        # gives its retained node what the constrained one has (and back).
        for nid, slots in retained_in_plane_slots(self.project).items():
            if nid in active:
                active[nid].update(slots)
        for nid, slots in auto_fixed_slots(self.project).items():
            if nid in active:
                active[nid].update(slots)
        # A support spring stiffens its own DOFs.
        for node in self.project.nodes:
            active[node.id].update(i for i, k in enumerate(node.spring) if k > 0)
        for link in self.project.rigid_links:
            shared = {0, 1, 2, 3, 4, 5} if link.kind == "beam" else {0, 1, 2}
            for nid in (link.retained_node, link.constrained_node):
                if nid in active:
                    active[nid].update(shared)

        problems: list[str] = []
        for node in self.project.nodes:
            for slot in self._dof_idx:
                if node.restraint[slot]:
                    continue  # restrained, no contribution needed
                if slot not in active[node.id]:
                    label = {0: "Ux", 1: "Uy", 2: "Uz", 3: "Rx", 4: "Ry", 5: "Rz"}[slot]
                    problems.append(
                        f"Node {node.id}, DOF {label}: no element "
                        f"contributes stiffness and DOF is unrestrained."
                    )
        if problems:
            hint = (
                "\n\nHint: pure-truss models should use ndm=2/ndf=2 "
                "(or ndm=3/ndf=3). File → New 2D Truss creates an ndf=2 "
                "project. For mixed truss+frame models, add a frame "
                "element that engages the listed rotational DOFs, or "
                "restrain them manually. A rotation every member releases at a "
                "joint (end releases) needs a support or a member that keeps it."
            )
            raise RuntimeError(
                "Singular stiffness matrix — the solve cannot run.\n" + "\n".join(problems) + hint
            )

    #: Components of one point of ``eleResponse(tag, "stresses")``: the section
    #: stress resultants N11, N22, N12, M11, M22, M12, V13, V23. A ShellMITC4
    #: reports four gauss points of these; they are averaged per element.
    STRESS_RESULTANTS = 8

    def _element_stress_resultants(self, element_id: int) -> np.ndarray | None:
        """One element's section stress resultants, averaged over its gauss points.

        Returns ``None`` for element types that do not answer — bars, trusses
        and zero-length elements have no section resultants — and for anything
        whose vector does not divide into whole resultants.

        This is only meaningful once the element has updated its section state,
        which happens when the analysis commits the step. `_run_static` and the
        pushover snapshot call ``ops.reactions()`` before reading, and that
        query is what materialises the state of a `Linear` solve as well: asking
        ``eleResponse`` straight after ``analyze`` on a `Linear` case returns
        zeros, asking it after ``reactions()`` returns the real resultants
        (measured — see `reports/SHELL_CONTOURS_PLAN_2026-10-09.md`).
        """
        try:
            raw = self._ops.eleResponse(element_id, "stresses")
        except Exception:
            return None
        if not raw:
            return None
        values = np.asarray(raw, dtype=float)
        if values.size == 0 or values.size % self.STRESS_RESULTANTS:
            return None
        return values.reshape(-1, self.STRESS_RESULTANTS).mean(axis=0)

    def _element_local_force(self, element_id: int) -> Any:
        """One element's end forces: ``localForce`` when it answers, else ``eleForce``.

        ``localForce`` is ``[N, V_y, V_z, T, M_y, M_z]`` per end in the element's
        local frame, which is what diagrams need; a zeroLength or truss element
        may only have the global ``eleForce``.
        """
        ops = self._ops
        try:
            forces = ops.eleResponse(element_id, "localForce")
        except Exception:
            forces = []
        if not forces:
            forces = ops.eleForce(element_id)
        return forces

    def _run_static(self, case: StaticCase) -> StaticResults:
        ops = self._ops
        self._emit_patterns_for_case(case.pattern_ids)
        self._setup_analysis(case)

        ndf = len(self._dof_idx)
        node_disp = {n.id: np.zeros((case.n_steps, ndf)) for n in self.project.nodes}
        node_reaction = {n.id: np.zeros((case.n_steps, ndf)) for n in self.project.nodes}
        element_forces: dict[int, np.ndarray] = {}
        element_stresses: dict[int, np.ndarray] = {}
        cuts = storey_cuts(self.project) if self.project.storeys else []
        element_nodes = {el.id: el.nodes for el in self.project.elements}
        ndm = self.project.ndm
        storey_shear = {cut.storey_id: np.zeros((case.n_steps, ndm)) for cut in cuts}
        section_cut_geometry = section_cuts(self.project)
        section_cut_forces = {g.cut_id: np.zeros((case.n_steps, 6)) for g in section_cut_geometry}
        node_coords = {n.id: n.coords for n in self.project.nodes}

        correct = self._needs_correction_solve(case, case.pattern_ids)
        thermal = self._thermal_end_forces(case)
        for step in range(case.n_steps):
            status = self._analyze_static_step(case, correct)
            if status != 0:
                raise RuntimeError(
                    f"Static analysis failed at step {step + 1}/{case.n_steps} "
                    f"(ops.analyze returned {status})."
                )
            ops.reactions()
            for node in self.project.nodes:
                for j, dof in enumerate(range(1, ndf + 1)):
                    node_disp[node.id][step, j] = ops.nodeDisp(node.id, dof) * self._dof_sign[j]
                node_reaction[node.id][step, :] = (
                    np.asarray(self._node_reactions(node.id, ndf), dtype=float) * self._dof_sign
                )
            for el in self.project.elements:
                forces = self._element_local_force(el.id)
                if el.id not in element_forces:
                    element_forces[el.id] = np.zeros((case.n_steps, len(forces)))
                element_forces[el.id][step, :] = forces
                for factor_of, fixed_end in thermal.get(el.id, ()):
                    element_forces[el.id][step, :] += factor_of(step) * fixed_end
                stresses = self._element_stress_resultants(el.id)
                if stresses is not None:
                    if el.id not in element_stresses:
                        element_stresses[el.id] = np.zeros(
                            (case.n_steps, self.STRESS_RESULTANTS),
                            dtype=float,
                        )
                    element_stresses[el.id][step, :] = stresses
            # Storey shears from the global end forces of the members each
            # storey cut crosses (``eleForce`` is global, ``localForce`` is not).
            global_forces: dict[int, Any] = {}
            for cut in cuts:
                for element_id, _lower in cut.members:
                    if element_id not in global_forces:
                        global_forces[element_id] = ops.eleForce(element_id)
                storey_shear[cut.storey_id][step, :] = cut_force(
                    cut, element_nodes, global_forces, ndm
                )
            for geometry in section_cut_geometry:
                for element_id, _positions in geometry.members:
                    if element_id not in global_forces:
                        global_forces[element_id] = ops.eleForce(element_id)
                section_cut_forces[geometry.cut_id][step, :] = cut_resultant(
                    geometry, element_nodes, global_forces, node_coords, ndm, ndf
                )
            self._progress(step + 1, case.n_steps)

        return StaticResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=case.n_steps,
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_forces=element_forces,
            element_stresses=element_stresses,
            storey_shear=storey_shear,
            section_cut_forces=section_cut_forces,
        )

    def _run_influence_line(self, case: InfluenceLineCase) -> InfluenceLineResults:
        """A unit load walked along ``case.path``: one linear static solve per stop.

        Each stop's load is a pattern of its own on a constant time series. For a
        linear model the solve after removing the previous pattern and adding the
        next gives exactly the response to the new load alone (the residual of
        the previous state is the previous load), so the model is built once.
        """
        from opensees_studio.core.influence import influence_positions

        ops = self._ops
        project = self.project
        if project.ndm == 2 and case.direction == "Y":
            raise ValueError(
                "A 2D model lives in the X-Z plane: the moving load cannot act along Y."
            )
        stops = influence_positions(project, case.path, case.stations)
        series_tag = max((ts.id for ts in project.time_series), default=0) + 1
        ops.timeSeries("Constant", series_tag)
        first_pattern = max((p.id for p in project.load_patterns), default=0) + 1
        self._setup_analysis(
            StaticCase(id=case.id, name=case.name, pattern_ids=[first_pattern], algorithm="Linear")
        )
        vector = np.zeros(3)
        vector["XYZ".index(case.direction)] = case.load
        elements = {el.id: el for el in project.elements}
        coords = {n.id: n.coords for n in project.nodes}
        ndf = len(self._dof_idx)
        n = len(stops)
        node_disp = {node.id: np.zeros((n, ndf)) for node in project.nodes}
        node_reaction = {node.id: np.zeros((n, ndf)) for node in project.nodes}
        element_forces: dict[int, np.ndarray] = {}
        for k, stop in enumerate(stops):
            tag = first_pattern + k
            if stop.node_id is not None:
                pattern = PlainLoadPattern(
                    id=tag,
                    time_series_id=series_tag,
                    nodal_loads=[
                        NodalLoad(
                            node_id=stop.node_id,
                            forces=(
                                float(vector[0]),
                                float(vector[1]),
                                float(vector[2]),
                                0.0,
                                0.0,
                                0.0,
                            ),
                        )
                    ],
                )
            else:
                el = elements[stop.element_id]
                axes = frame_local_axes(project.ndm, coords[el.nodes[0]], coords[el.nodes[1]])
                assert axes is not None  # a member of the path has a length
                px, py, pz = (float(np.dot(vector, axis)) for axis in axes)
                pattern = PlainLoadPattern(
                    id=tag,
                    time_series_id=series_tag,
                    point_loads=[
                        PointElementLoad(
                            element_id=stop.element_id, px=px, py=py, pz=pz, x=stop.fraction
                        )
                    ],
                )
            self._emit_pattern(pattern)
            status = ops.analyze(1)
            if status != 0:
                raise RuntimeError(
                    f"Influence line: the solve with the load at stop {k + 1}/{n} failed "
                    f"(ops.analyze returned {status})."
                )
            ops.reactions()
            for node in project.nodes:
                for j in range(ndf):
                    node_disp[node.id][k, j] = ops.nodeDisp(node.id, j + 1) * self._dof_sign[j]
                node_reaction[node.id][k, :] = (
                    np.asarray(self._node_reactions(node.id, ndf), dtype=float) * self._dof_sign
                )
            for el in project.elements:
                forces = self._element_local_force(el.id)
                if el.id not in element_forces:
                    element_forces[el.id] = np.zeros((n, len(forces)))
                element_forces[el.id][k, :] = forces
            ops.remove("loadPattern", tag)
            self._progress(k + 1, n)
        return InfluenceLineResults(
            case_id=case.id,
            case_name=case.name,
            distances=np.asarray([s.distance for s in stops], dtype=float),
            element_ids=np.asarray([s.element_id for s in stops], dtype=int),
            fractions=np.asarray([s.fraction for s in stops], dtype=float),
            load=case.load,
            direction=case.direction,
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_forces=element_forces,
        )

    def _thermal_end_forces(
        self, case: StaticCase
    ) -> dict[int, list[tuple[Callable[[int], float], np.ndarray]]]:
        """Each heated member's fixed-end forces and the pattern factor at a step.

        The member's real end forces are what OpenSees reports plus these (see
        :mod:`core.thermal`). The factor is the pattern's time series at the
        step's load factor, so a ramp in N steps adds them in N parts.
        """
        out: dict[int, list[tuple[Callable[[int], float], np.ndarray]]] = {}
        patterns = {p.id: p for p in self.project.load_patterns}
        series = {ts.id: ts for ts in self.project.time_series}
        for pid in case.pattern_ids:
            pattern = patterns.get(pid)
            if not isinstance(pattern, PlainLoadPattern) or not pattern.temperature_loads:
                continue
            ts = series.get(pattern.time_series_id)
            if case.integrator != "LoadControl" or not isinstance(
                ts, LinearTimeSeries | ConstantTimeSeries
            ):
                raise ValueError(
                    f"Pattern {pattern.name or pid} carries temperature loads: they run under "
                    "LoadControl with a Linear or Constant time series only."
                )
            if isinstance(ts, ConstantTimeSeries):
                factor = float(ts.factor)

                def factor_of(step: int, value: float = factor) -> float:
                    return value

            else:
                scale = float(ts.factor) * case.load_factor_increment

                def factor_of(step: int, value: float = scale) -> float:
                    return (step + 1) * value

            for thermal in pattern.temperature_loads:
                out.setdefault(thermal.element_id, []).append(
                    (factor_of, fixed_end_forces(self.project, thermal))
                )
        return out

    def _run_pushover(self, case: PushoverCase) -> PushoverResults:
        """Monotonic displacement-controlled pushover.

        Steps the control DOF from 0 to ``target_disp`` in increments of
        ``step_size`` (sign-aware: negative target → negative increments).
        At each step we:
        - run ops.analyze(1)
        - record the control-DOF displacement (x-axis value)
        - sum reactions at base_nodes projected onto the control DOF
          direction; negated = applied base shear (y-axis value)
        - snapshot node displacements and element local forces
        """
        from opensees_studio.core import ConstantTimeSeries

        ops = self._ops

        # Base-node list defaults to every restrained node.
        base_nodes = (
            list(case.base_nodes)
            if case.base_nodes
            else [n.id for n in self.project.nodes if n.is_restrained]
        )
        if not base_nodes:
            raise RuntimeError(
                "Pushover needs at least one restrained (base) node for "
                "reaction summation. Add a support or specify base_nodes.",
            )

        ndf = len(self._dof_idx)
        # Number of analysis steps — sign-aware increment.
        sign = 1.0 if case.target_disp >= 0.0 else -1.0
        dU = sign * case.step_size
        n_steps = int(abs(case.target_disp) / case.step_size)
        if n_steps == 0:
            raise ValueError(
                f"Pushover step_size ({case.step_size}) larger than target "
                f"({case.target_disp}); would run zero steps.",
            )

        # ── Preload (gravity / axial) ──────────────────────────────
        # Preferred path: explicit ``preload_case_ids`` — each runs its
        # patterns through a full LoadControl ramp, matching the Tcl
        # "analyze 10; loadConst -time 0.0" recipe.
        # Legacy path (no preload_case_ids): fall back to splitting
        # ``pattern_ids`` by TimeSeries kind — Constant patterns become
        # a single zero-step LoadControl preload, Linear patterns
        # become the DisplacementControl reference.
        preload_ids = list(getattr(case, "preload_case_ids", []) or [])
        if preload_ids:
            self._run_preload_sequence(preload_ids, case.id)
            linear_ids = list(case.pattern_ids)
        else:
            const_ids: list[int] = []
            linear_ids = []
            ts_by_id = {ts.id: ts for ts in self.project.time_series}
            for pid in case.pattern_ids:
                pat = next(p for p in self.project.load_patterns if p.id == pid)
                ts_id = getattr(pat, "time_series_id", None)
                ts = ts_by_id.get(ts_id) if ts_id is not None else None
                if isinstance(ts, ConstantTimeSeries):
                    const_ids.append(pid)
                else:
                    linear_ids.append(pid)
            if const_ids:
                self._emit_patterns_for_case(const_ids)
                ops.system(case.system, *case.system_args)
                ops.numberer(case.numberer)
                self._constraints(case)
                ops.test(case.test, *test_args(case.test, case.tolerance, case.max_iter))
                ops.algorithm(case.algorithm, *case.algorithm_args)
                ops.integrator("LoadControl", 0.0)
                ops.analysis("Static")
                status = ops.analyze(1)
                if status != 0:
                    raise RuntimeError(
                        "Pushover preload step (constant patterns) failed "
                        "to converge. Loosen test tolerance or check the "
                        "axial magnitude.",
                    )
                ops.loadConst("-time", 0.0)

        # Emit Linear reference patterns (after preload so they don't
        # accumulate into the locked baseline).
        if linear_ids:
            self._emit_patterns_for_case(linear_ids)

        # Configure analysis — DisplacementControl integrator.
        ops.system(case.system, *case.system_args)
        ops.numberer(case.numberer)
        self._constraints(case)
        ops.test(case.test, *test_args(case.test, case.tolerance, case.max_iter))
        ops.algorithm(case.algorithm, *case.algorithm_args)
        ops.integrator(
            "DisplacementControl",
            case.control_node,
            case.control_dof,
            dU * float(self._dof_sign[case.control_dof - 1]),
        )
        ops.analysis("Static")

        # Allocate output arrays, including step 0 (initial state).
        control_disp = np.zeros(n_steps + 1)
        base_shear = np.zeros(n_steps + 1)
        node_disp = {n.id: np.zeros((n_steps + 1, ndf)) for n in self.project.nodes}
        element_forces: dict[int, np.ndarray] = {}
        element_stresses: dict[int, np.ndarray] = {}

        def _snapshot(step: int) -> None:
            ops.reactions()
            # Sum reactions at base nodes in the control direction; negate
            # so positive base_shear means "applied load to the right".
            bs = 0.0
            control_sign = float(self._dof_sign[case.control_dof - 1])
            for nid in base_nodes:
                bs += float(self._node_reactions(nid, ndf)[case.control_dof - 1]) * control_sign
            base_shear[step] = -bs
            control_disp[step] = control_sign * float(
                ops.nodeDisp(case.control_node, case.control_dof),
            )
            for node in self.project.nodes:
                for j, dof in enumerate(range(1, ndf + 1)):
                    node_disp[node.id][step, j] = ops.nodeDisp(node.id, dof) * self._dof_sign[j]
            for el in self.project.elements:
                try:
                    forces = ops.eleResponse(el.id, "localForce")
                except Exception:
                    forces = []
                if not forces:
                    try:
                        forces = ops.eleForce(el.id)
                    except Exception:
                        continue
                if el.id not in element_forces:
                    element_forces[el.id] = np.zeros(
                        (n_steps + 1, len(forces)),
                        dtype=float,
                    )
                element_forces[el.id][step, :] = forces
                stresses = self._element_stress_resultants(el.id)
                if stresses is not None:
                    if el.id not in element_stresses:
                        element_stresses[el.id] = np.zeros(
                            (n_steps + 1, self.STRESS_RESULTANTS),
                            dtype=float,
                        )
                    element_stresses[el.id][step, :] = stresses

        # Step 0: initial state (all zeros in the linear case, but we
        # still record so the curve starts at the origin cleanly).
        _snapshot(0)

        for step in range(1, n_steps + 1):
            status = ops.analyze(1)
            if status != 0:
                # Convergence fallback mirrors the OpenSees portal-frame
                # tutorials: initial-tangent Newton, then Broyden, then
                # Newton with line search.
                ops.test(case.test, *test_args(case.test, case.tolerance, 2000))
                ops.algorithm("Newton", "-initial")
                status = ops.analyze(1)
                if status != 0:
                    ops.algorithm("Broyden", 8)
                    status = ops.analyze(1)
                if status != 0:
                    ops.algorithm("NewtonLineSearch", 0.8)
                    status = ops.analyze(1)
                ops.test(case.test, *test_args(case.test, case.tolerance, case.max_iter))
                ops.algorithm(case.algorithm, *case.algorithm_args)
            if status != 0:
                # Still failed — trim output to where we got, then stop.
                control_disp = control_disp[:step]
                base_shear = base_shear[:step]
                for nid in node_disp:
                    node_disp[nid] = node_disp[nid][:step]
                for eid in element_forces:
                    element_forces[eid] = element_forces[eid][:step]
                for eid in element_stresses:
                    element_stresses[eid] = element_stresses[eid][:step]
                break
            _snapshot(step)
            self._progress(step, n_steps)

        return PushoverResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=len(control_disp) - 1,
            control_node=case.control_node,
            control_dof=case.control_dof,
            control_disp=control_disp,
            base_shear=base_shear,
            node_disp=node_disp,
            element_forces=element_forces,
            element_stresses=element_stresses,
        )

    def _run_response_spectrum(self, case: ResponseSpectrumCase) -> ResponseSpectrumResults:
        """Re-run the referenced modal case, then combine via SRSS/CQC.

        We delegate to the spectrum service for the math; the runner's
        only job is finding the linked ModalCase + ResponseSpectrum and
        wiring up :class:`ResponseSpectrumResults`.
        """
        from opensees_studio.services.spectrum import (
            combine_modal_field,
            combine_modal_response,
            mass_participation,
            modal_equivalent_loads,
        )

        modal_case = next(
            (
                c
                for c in self.project.analyses
                if isinstance(c, ModalCase) and c.id == case.modal_case_id
            ),
            None,
        )
        if modal_case is None:
            raise ValueError(
                f"ResponseSpectrum case references modal_case_id="
                f"{case.modal_case_id}, but no such ModalCase exists.",
            )
        spectrum = next(
            (s for s in self.project.spectra if s.id == case.spectrum_id),
            None,
        )
        if spectrum is None:
            raise ValueError(
                f"ResponseSpectrum case references spectrum_id="
                f"{case.spectrum_id}, but no such ResponseSpectrum exists.",
            )

        modal_results = self._run_modal(modal_case)

        warnings: list[str] = []
        damping: float | None = None
        if case.combination == "CQC":
            damping = (
                case.damping_ratio if case.damping_ratio is not None else spectrum.damping_ratio
            )
            if damping <= 0.0:
                warnings.append(
                    f"CQC needs a positive modal damping ratio; the case leaves it to the "
                    f"spectrum and spectrum '{spectrum.name}' has {spectrum.damping_ratio:g}. "
                    f"Using {DEFAULT_MODAL_DAMPING:g}."
                )
                damping = DEFAULT_MODAL_DAMPING

        modes = mass_participation(self.project, modal_results, case.direction)
        combined, modes = combine_modal_response(
            modes,
            spectrum,
            modal_results,
            case.direction,
            method=case.combination,
            damping=damping,
        )

        # Reactions and element forces: the static response to each mode's
        # equivalent load, combined across modes with the rule of the case.
        per_mode = self._modal_static_responses(
            modal_equivalent_loads(self.project, modal_results, modes)
        )
        rule_damping = damping if damping is not None else spectrum.damping_ratio
        peak = {
            name: combine_modal_field(modes, by_mode, method=case.combination, damping=rule_damping)
            for name, by_mode in per_mode.items()
        }

        if case.combination == "SRSS":
            pairs = closely_spaced_pairs(
                [m.angular_frequency for m in modes], ratio=case.closely_spaced_ratio
            )
            if pairs:
                listed = ", ".join(
                    f"modes {modes[i].mode_number} and {modes[j].mode_number} (ratio {r:.3f})"
                    for i, j, r in pairs
                )
                warnings.append(
                    f"SRSS with closely spaced modes (frequency ratio at or above "
                    f"{case.closely_spaced_ratio:g}): {listed}. SRSS ignores their correlation "
                    f"and its result depends on the eigen basis inside such a pair; use CQC."
                )

        return ResponseSpectrumResults(
            case_id=case.id,
            case_name=case.name,
            direction=case.direction,
            combination=case.combination,
            combined_disp=combined,
            node_reaction=peak["node_reaction"],
            element_forces=peak["element_forces"],
            element_stresses=peak["element_stresses"],
            modes=modes,
            solver=modal_results.solver,
            damping_ratio=damping,
            warnings=warnings,
        )

    def _modal_static_responses(
        self, loads_by_mode: dict[int, dict[int, np.ndarray]]
    ) -> dict[str, dict[int, dict[int, np.ndarray]]]:
        """Reactions, element forces and shell resultants under each mode's static load.

        ``loads_by_mode`` maps a mode number to its nodal load vectors (see
        ``services.spectrum.modal_equivalent_loads``). Each mode is one linear
        static solve of the built model, with the loads on free DOFs only (the
        mode shape is zero on a restrained one). Returns ``{"node_reaction" |
        "element_forces" | "element_stresses": {mode: {id: vector}}}``. It runs
        after the eigen solve and never calls ``eigen``, so it leaves the
        eigen determinism rule alone.
        """
        ops = self._ops
        ndf = len(self._dof_idx)
        out: dict[str, dict[int, dict[int, np.ndarray]]] = {
            "node_reaction": {},
            "element_forces": {},
            "element_stresses": {},
        }
        ops.wipeAnalysis()
        for mode, loads in loads_by_mode.items():
            ops.timeSeries("Constant", 1)
            ops.pattern("Plain", 1, 1)
            for nid, vec in loads.items():
                full = np.zeros(ndf)
                full[: vec.size] = vec
                # Mode shapes carry global signs; OpenSees takes its own.
                ops.load(nid, *[float(x) for x in full * self._dof_sign])
            ops.system("BandGeneral")
            ops.numberer("RCM")
            ops.constraints(self._constraints_handler(_MODAL_STATIC_CASE))
            ops.test("NormDispIncr", 1.0e-12, 10)
            ops.algorithm("Linear")
            ops.integrator("LoadControl", 1.0)
            ops.analysis("Static")
            status = ops.analyze(1)
            if status != 0:
                raise RuntimeError(
                    f"The static solve for the load of mode {mode} failed "
                    f"(ops.analyze returned {status})."
                )
            ops.reactions()
            out["node_reaction"][mode] = {
                n.id: np.asarray(self._node_reactions(n.id, ndf), dtype=float)
                for n in self.project.nodes
            }
            forces: dict[int, np.ndarray] = {}
            stresses: dict[int, np.ndarray] = {}
            for el in self.project.elements:
                forces[el.id] = np.asarray(self._element_local_force(el.id), dtype=float)
                resultants = self._element_stress_resultants(el.id)
                if resultants is not None:
                    stresses[el.id] = resultants
            out["element_forces"][mode] = forces
            out["element_stresses"][mode] = stresses
            ops.wipeAnalysis()
            ops.remove("loadPattern", 1)
            ops.remove("timeSeries", 1)
            ops.reset()
        return out

    def _run_modal(self, case: ModalCase) -> ModalResults:
        """Eigenvalue analysis with history-independent results.

        The solver comes from :func:`core.modal.resolve_modal_solver`:
        dense ``fullGenLapack`` at or below the free DOF threshold (a direct
        method, bit-identical on every call), ARPACK above it (the CLI runs
        such a case as the first eigen call of a fresh process, because
        ARPACK keeps its start vector across calls). An explicit solver is
        honoured; ARPACK still falls back to dense when
        ``2 * n_modes >= n_free`` (it aborts with ``_saupd info = -9999``).
        Degenerate groups (repeated eigenvalues) are made mass-orthogonal
        and every mode shape is sign-normalized (largest absolute component
        positive, ties broken by the lowest DOF index).
        """
        ops = self._ops
        ndf = len(self._dof_idx)

        n_free = free_dof_count(self.project)
        solver, _reason = resolve_modal_solver(case.solver, n_free, case.n_modes)

        eigenvalues = np.array(ops.eigen(f"-{solver}", case.n_modes), dtype=float)

        raw_shapes: dict[int, dict[int, np.ndarray]] = {}
        for mode in range(1, case.n_modes + 1):
            raw_shapes[mode] = {
                node.id: np.array(
                    [ops.nodeEigenvector(node.id, mode, dof) for dof in range(1, ndf + 1)],
                    dtype=float,
                )
                * self._dof_sign
                for node in self.project.nodes
            }
        node_mass = {
            node.id: np.array([self._node_mass[node.id][i] for i in self._dof_idx], dtype=float)
            for node in self.project.nodes
        }
        # A repeated eigenvalue gives an arbitrary, with the dense solver even
        # mass-oblique, basis of its eigenspace: make it mass-orthogonal so
        # participation and CQC are basis-invariant, then fix every sign.
        mode_shapes = {
            mode: normalize_mode_sign(shape)
            for mode, shape in orthogonalize_degenerate_modes(
                eigenvalues, raw_shapes, node_mass
            ).items()
        }

        return ModalResults(
            case_id=case.id,
            case_name=case.name,
            eigenvalues=eigenvalues,
            mode_shapes=mode_shapes,
            solver=solver,
            n_free_dof=n_free,
        )

    def _run_transient(self, case: TransientCase, results_dir: Path) -> TransientResults:
        ops = self._ops
        results_dir.mkdir(parents=True, exist_ok=True)
        # OpenSees never gets results_dir itself: it may hold characters
        # OpenSees cannot open on Windows. Recorders write into an ASCII
        # staging directory and Python copies the files to recorder_dir.
        recorder_dir = results_dir / "recorders"
        with staging_dir() as stage:
            try:
                return self._run_transient_staged(case, results_dir, recorder_dir, stage)
            finally:
                # Close OpenSees' file handles before the stage is removed
                # (a no-op when the run already flushed its recorders).
                ops.remove("recorders")

    def _run_transient_staged(
        self, case: TransientCase, results_dir: Path, recorder_dir: Path, stage: Path
    ) -> TransientResults:
        import math as _math

        import h5py

        ops = self._ops

        # Preload phase — run each referenced StaticCase to completion
        # before the transient recorders open, so the static solve's
        # intermediate steps don't bloat the time-history file.
        self._run_preload_sequence(
            getattr(case, "preload_case_ids", []) or [],
            case.id,
        )

        # First-mode Rayleigh βK — compute *after* preload so λ₁ reflects
        # the currently loaded tangent stiffness (for linear models this
        # is the same as the unloaded value, but for PDelta frames it
        # picks up the geometric-softening contribution).
        beta_k_override: float | None = None
        damping = getattr(case, "rayleigh_mode1_damping", None)
        if damping is not None:
            # For mode-1 Rayleigh calibration we only need the first
            # eigenvalue. Using the dense solver here avoids ARPACK's
            # small-model failure mode (common in 1-element / 1-storey
            # tutorials) and keeps the damping workflow deterministic.
            eigs = ops.eigen("-fullGenLapack", 1)
            lam1 = eigs[0] if hasattr(eigs, "__getitem__") else eigs
            if lam1 <= 0.0:
                raise RuntimeError(
                    f"TransientCase {case.id}: first eigenvalue is "
                    f"{lam1:.3e} — cannot compute mode-1 Rayleigh damping."
                )
            beta_k_override = 2.0 * float(damping) / _math.sqrt(float(lam1))

        # Modal damping: ``eigen N`` (solver from resolve_modal_solver, the
        # one eigen call of this case) then ``modalDamping ζ``.
        if case.modal_damping is not None:
            n_free = free_dof_count(self.project)
            n_modes = min(case.modal_damping_modes, n_free)
            if n_modes < 1:
                raise RuntimeError(
                    f"TransientCase {case.id}: the model has no free DOF to damp modally."
                )
            solver, _reason = resolve_modal_solver(SOLVER_AUTO, n_free, n_modes)
            ops.eigen(f"-{solver}", n_modes)
            ops.modalDamping(float(case.modal_damping))

        # Drop preload patterns the user flagged for removal (classic
        # ``remove loadPattern`` free-vibration idiom).
        for pid in getattr(case, "remove_patterns", []) or []:
            ops.remove("loadPattern", pid)

        # One recorder per quantity for all nodes, and one for the local
        # forces of all elements (hysteresis loops), whatever the model size:
        # every recorder keeps its file open for the whole run and the C
        # runtime allows about 509 open files, so one file per node and
        # element silently lost output on larger models. The "-time" flag
        # prepends the time column to every row. Python splits the columns
        # into the per-node and per-element datasets afterwards.
        node_ids = [n.id for n in self.project.nodes]
        dofs = list(range(1, len(self._dof_idx) + 1))
        node_files = {kind: stage / f"nodes_{kind}.out" for kind in ("disp", "vel", "accel")}
        for kind, path in node_files.items():
            ops.recorder(
                "Node", "-file", str(path), "-time", "-node", *node_ids, "-dof", *dofs, kind
            )
        elem_ids = [el.id for el in self.project.elements]
        elem_file = stage / "elements_localForce.out"
        if elem_ids:
            ops.recorder(
                "Element", "-file", str(elem_file), "-time", "-ele", *elem_ids, "localForce"
            )

        self._emit_patterns_for_case(case.pattern_ids)
        self._setup_analysis(case)
        # If a mode-1 βK was computed, re-issue ``ops.rayleigh`` with the
        # calibrated coefficient — this overrides whatever _setup_analysis
        # emitted from ``case.rayleigh_beta_k``.
        if beta_k_override is not None:
            ops.rayleigh(
                float(case.rayleigh_alpha_m),
                beta_k_override,
                0.0,
                0.0,
            )

        # Step-by-step with a ModifiedNewton -initial fallback on any
        # step the configured Newton-type algorithm fails to converge.
        # Matches the OpenSees RC Portal Earthquake example's while-
        # loop retry. If the fallback also fails we stop the transient
        # where we got — the recorders already hold the partial
        # history, which is still useful (shows collapse / divergence
        # point) just like the Tcl reference does.
        steps_completed = 0
        for _step in range(case.n_steps):
            status = ops.analyze(1, case.dt)
            if status != 0:
                ops.test(case.test, *test_args(case.test, case.tolerance, 1000))
                ops.algorithm("Newton", "-initial")
                status = ops.analyze(1, case.dt)
                if status != 0:
                    ops.algorithm("Broyden", 8)
                    status = ops.analyze(1, case.dt)
                if status != 0:
                    ops.algorithm("NewtonLineSearch", 0.8)
                    status = ops.analyze(1, case.dt)
                ops.test(case.test, *test_args(case.test, case.tolerance, case.max_iter))
                ops.algorithm(case.algorithm, *case.algorithm_args)
            if status != 0:
                break
            # Counts successful steps only, so enumerate() would be wrong here.
            # Reported as TransientResults.n_steps; recorders write one row
            # per committed step, so the history arrays have the same length.
            steps_completed += 1
            self._progress(steps_completed, case.n_steps)

        # Flush recorders, then consolidate.
        ops.wipeAnalysis()
        ops.remove("recorders")

        if steps_completed == 0:
            # Nothing was committed, so the recorder files are empty and
            # there is no history to consolidate.
            raise RuntimeError(
                f"Transient analysis failed at step 1/{case.n_steps}: "
                "no step converged, even with the fallback algorithms."
            )

        # A recorder that could not open its file leaves nothing behind and
        # OpenSees reports no error: never hand back a silently empty history.
        staged = [*node_files.values(), *([elem_file] if elem_ids else [])]
        check_recorder_output(staged, steps_completed)

        # Column layout: time, then node by node (each with its ndf DOF), and
        # element by element with the width of its localForce vector (0 for
        # an element without that response, as in the recorder itself).
        ndof = len(dofs)
        node_tables = {
            kind: load_recorder_table(path, steps_completed, 1 + ndof * len(node_ids))
            for kind, path in node_files.items()
        }
        widths = [len(ops.eleResponse(eid, "localForce") or []) for eid in elem_ids]
        elem_table = (
            load_recorder_table(elem_file, steps_completed, 1 + sum(widths)) if elem_ids else None
        )

        # The raw recorder files keep their place next to the HDF5 file; they
        # are placed first so a failure here leaves the previous HDF5 intact.
        place_files(staged, recorder_dir)

        h5_path = results_dir / f"case_{case.id}.h5"
        tmp_h5 = results_dir / f"case_{case.id}.h5.{os.getpid()}.tmp"
        try:
            with h5py.File(tmp_h5, "w") as f:
                f.create_dataset("time", data=node_tables["disp"][:, 0])
                for i, nid in enumerate(node_ids):
                    cols = slice(1 + i * ndof, 1 + (i + 1) * ndof)
                    for kind, table in node_tables.items():
                        # Recorders write OpenSees' signs; results carry the global ones.
                        data = table[:, cols] * self._dof_sign[:ndof]
                        f.create_dataset(f"nodes/{nid}/{kind}", data=data)
                if elem_table is not None:
                    start = 1
                    for eid, width in zip(elem_ids, widths, strict=True):
                        f.create_dataset(
                            f"elements/{eid}/forces", data=elem_table[:, start : start + width]
                        )
                        start += width
            os.replace(tmp_h5, h5_path)
        except BaseException:
            tmp_h5.unlink(missing_ok=True)
            raise

        return TransientResults(
            case_id=case.id,
            case_name=case.name,
            h5_path=h5_path,
            n_steps=steps_completed,
            dt=case.dt,
            n_steps_requested=case.n_steps,
        )
