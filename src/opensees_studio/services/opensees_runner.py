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
    → uniaxialMaterial / nDMaterial × M
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

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from opensees_studio.core import (
    Concrete01,
    Concrete02,
    ConstantTimeSeries,
    CorotTrussElement,
    DispBeamColumn,
    ElasticBeamColumn,
    ElasticIsotropic,
    ElasticPP,
    ElasticSection,
    ElasticUniaxial,
    FiberSection,
    ForceBeamColumn,
    LinearTimeSeries,
    ModalCase,
    PathTimeSeries,
    PlainLoadPattern,
    Project,
    StaticCase,
    Steel01,
    Steel02,
    TransientCase,
    TrussElement,
    UniformExcitationPattern,
    ZeroLengthElement,
)
from opensees_studio.services.results import (
    ModalResults,
    StaticResults,
    TransientResults,
)


# ─────────────────────── DOF-index helper ───────────────────────
def _dof_indices(ndm: int, ndf: int) -> tuple[int, ...]:
    """Map (ndm, ndf) onto positions in the canonical 6-DOF storage.

    The internal Node carries 6-component coords, mass, restraint.
    Different OpenSees model dimensions consume different subsets:

    - (2, 2): 2D truss               → (Ux, Uy)               = (0, 1)
    - (2, 3): 2D frame               → (Ux, Uy, Rz)           = (0, 1, 5)
    - (3, 3): 3D truss / brick       → (Ux, Uy, Uz)           = (0, 1, 2)
    - (3, 6): 3D frame               → (Ux, Uy, Uz, Rx, Ry, Rz)= (0..5)
    """
    table = {
        (2, 2): (0, 1),
        (2, 3): (0, 1, 5),
        (3, 3): (0, 1, 2),
        (3, 6): (0, 1, 2, 3, 4, 5),
    }
    if (ndm, ndf) not in table:
        raise ValueError(f"Unsupported (ndm, ndf): ({ndm}, {ndf}).")
    return table[(ndm, ndf)]


# ─────────────────────── runner ───────────────────────
class OpenSeesRunner:
    """Translator + executor. Instantiate with a project, then ``run(case)``."""

    def __init__(self, project: Project, ops_module: Any | None = None) -> None:
        """
        Args:
            project: The model to translate.
            ops_module: ``openseespy.opensees`` by default; override with a
                mock in tests to verify the emitted command sequence
                without invoking the real solver.
        """
        if ops_module is None:
            import openseespy.opensees as ops_module  # local import for testability
        self._ops = ops_module
        self.project = project
        self._dof_idx: tuple[int, ...] = _dof_indices(project.ndm, project.ndf)
        self._geom_transf_tags: dict[str, int] = {}
        self._element_geom_transf_tag: dict[int, int] = {}

    # ─────────────────────── public API ───────────────────────
    def build(self) -> None:
        """Emit all model-construction commands. Idempotent (wipes first)."""
        self.project.validate_references()

        ops = self._ops
        ops.wipe()
        ops.model("basic", "-ndm", self.project.ndm, "-ndf", self.project.ndf)

        for node in self.project.nodes:
            self._emit_node(node)
        for node in self.project.nodes:
            if node.is_restrained:
                self._emit_fix(node)

        # Mass: emit only if any non-zero
        for node in self.project.nodes:
            if any(node.mass):
                self._emit_mass(node)

        for material in self.project.materials:
            self._emit_material(material)

        for section in self.project.sections:
            self._emit_section(section)

        # Geometric transformations needed by frame elements
        self._allocate_and_emit_geom_transfs()

        for element in self.project.elements:
            self._emit_element(element)

    def run(self, case: Any, results_dir: Path | None = None) -> Any:
        """Build the model and run the requested analysis case.

        Returns:
            :class:`StaticResults` / :class:`ModalResults` / :class:`TransientResults`
            depending on case type.
        """
        self.build()
        if isinstance(case, StaticCase):
            return self._run_static(case)
        if isinstance(case, ModalCase):
            return self._run_modal(case)
        if isinstance(case, TransientCase):
            target = results_dir or Path(tempfile.mkdtemp(prefix="osstudio_"))
            return self._run_transient(case, target)
        raise TypeError(f"Unsupported analysis case type: {type(case).__name__}")

    # ─────────────────────── nodes / fixes / mass ───────────────────────
    def _emit_node(self, node: Any) -> None:
        coords = node.coords[: self.project.ndm]
        self._ops.node(node.id, *coords)

    def _emit_fix(self, node: Any) -> None:
        flags = tuple(int(node.restraint[i]) for i in self._dof_idx)
        self._ops.fix(node.id, *flags)

    def _emit_mass(self, node: Any) -> None:
        m = tuple(node.mass[i] for i in self._dof_idx)
        self._ops.mass(node.id, *m)

    # ─────────────────────── materials ───────────────────────
    def _emit_material(self, mat: Any) -> None:
        ops = self._ops
        match mat:
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
                    "Steel02", mat.id, mat.Fy, mat.E0, mat.b, mat.R0, mat.cR1, mat.cR2
                )
            case Concrete01():
                ops.uniaxialMaterial(
                    "Concrete01", mat.id, mat.fpc, mat.epsc0, mat.fpcu, mat.epsU
                )
            case Concrete02():
                ops.uniaxialMaterial(
                    "Concrete02", mat.id,
                    mat.fpc, mat.epsc0, mat.fpcu, mat.epsU,
                    mat.lambda_, mat.ft, mat.Ets,
                )
            case ElasticPP():
                args = [mat.E, mat.epsy_pos]
                if mat.epsy_neg is not None or mat.eps0 != 0.0:
                    args.append(mat.epsy_neg if mat.epsy_neg is not None else -mat.epsy_pos)
                    args.append(mat.eps0)
                ops.uniaxialMaterial("ElasticPP", mat.id, *args)
            case ElasticIsotropic():
                ops.nDMaterial("ElasticIsotropic", mat.id, mat.E, mat.nu, mat.rho)
            case _:
                raise NotImplementedError(f"Material type not yet handled: {type(mat).__name__}")

    # ─────────────────────── sections ───────────────────────
    def _emit_section(self, sec: Any) -> None:
        ops = self._ops
        match sec:
            case ElasticSection():
                if self.project.ndm == 2:
                    ops.section("Elastic", sec.id, sec.E, sec.A, sec.Iz)
                else:
                    if sec.Iy is None or sec.G is None or sec.J is None:
                        raise ValueError(
                            f"ElasticSection {sec.id} needs Iy, G, J for 3D models."
                        )
                    ops.section("Elastic", sec.id, sec.E, sec.A, sec.Iz, sec.Iy, sec.G, sec.J)
            case FiberSection():
                if sec.GJ is not None:
                    ops.section("Fiber", sec.id, "-GJ", sec.GJ)
                else:
                    ops.section("Fiber", sec.id)
                for fb in sec.fibres:
                    ops.fiber(fb.y, fb.z, fb.area, fb.material_id)
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

        frame_types = (ElasticBeamColumn, ForceBeamColumn, DispBeamColumn)
        node_coords = {n.id: np.array(n.coords, dtype=float) for n in self.project.nodes}

        # Allocate (transf_type, vecxz_tuple) → tag, lazily.
        combo_to_tag: dict[tuple[str, tuple[float, float, float]], int] = {}
        self._element_geom_transf_tag: dict[int, int] = {}
        next_tag = 1

        for el in self.project.elements:
            if not isinstance(el, frame_types):
                continue
            if self.project.ndm == 2:
                key = (el.geom_transf, (0.0, 0.0, 0.0))   # vecxz unused in 2D
                if key not in combo_to_tag:
                    combo_to_tag[key] = next_tag
                    self._ops.geomTransf(el.geom_transf, next_tag)
                    next_tag += 1
                self._element_geom_transf_tag[el.id] = combo_to_tag[key]
                continue

            # 3D: pick vecxz orthogonal to the element axis.
            p0 = node_coords[el.nodes[0]]
            p1 = node_coords[el.nodes[1]]
            axis = p1 - p0
            length = float(np.linalg.norm(axis))
            if length < 1e-12:
                # Degenerate element; fall back to horizontal default.
                vecxz = (0.0, 0.0, 1.0)
            else:
                axis_unit = axis / length
                # If the axis is closer to global Z than to global X,
                # use vecxz = (1, 0, 0). Otherwise (0, 0, 1).
                if abs(axis_unit[2]) > abs(axis_unit[0]):
                    vecxz = (1.0, 0.0, 0.0)
                else:
                    vecxz = (0.0, 0.0, 1.0)

            key = (el.geom_transf, vecxz)
            if key not in combo_to_tag:
                combo_to_tag[key] = next_tag
                self._ops.geomTransf(el.geom_transf, next_tag, *vecxz)
                next_tag += 1
            self._element_geom_transf_tag[el.id] = combo_to_tag[key]

        # Backward-compat for tests that read _geom_transf_tags.
        self._geom_transf_tags = {k[0]: v for k, v in combo_to_tag.items()}

    # ─────────────────────── elements ───────────────────────
    def _emit_element(self, el: Any) -> None:
        ops = self._ops
        match el:
            case TrussElement():
                ops.element("truss", el.id, *el.nodes, el.area, el.material_id, "-rho", el.rho)
            case CorotTrussElement():
                ops.element("corotTruss", el.id, *el.nodes, el.area, el.material_id, "-rho", el.rho)
            case ElasticBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.element(
                    "elasticBeamColumn", el.id, *el.nodes, el.section_id, tag,
                    "-mass", el.rho,
                )
            case ForceBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.beamIntegration(
                    "Lobatto", el.id, el.section_id, el.integration_points
                )
                ops.element(
                    "forceBeamColumn", el.id, *el.nodes, tag, el.id,
                    "-iter", el.max_iter, el.tolerance,
                )
            case DispBeamColumn():
                tag = self._element_geom_transf_tag[el.id]
                ops.beamIntegration(
                    "Lobatto", el.id, el.section_id, el.integration_points
                )
                ops.element("dispBeamColumn", el.id, *el.nodes, tag, el.id)
            case ZeroLengthElement():
                ops.element(
                    "zeroLength", el.id, *el.nodes,
                    "-mat", *el.material_ids,
                    "-dir", *el.dofs,
                )
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
                if ts.dt is not None:
                    ops.timeSeries(
                        "Path", ts.id, "-dt", ts.dt, "-values", *ts.values,
                        "-factor", ts.factor,
                    )
                elif ts.times is not None:
                    ops.timeSeries(
                        "Path", ts.id, "-time", *ts.times, "-values", *ts.values,
                        "-factor", ts.factor,
                    )
                else:
                    raise ValueError(
                        f"PathTimeSeries {ts.id}: either ``dt`` or ``times`` is required."
                    )
            case _:
                raise NotImplementedError(f"TimeSeries type not yet handled: {type(ts).__name__}")

    def _emit_pattern(self, pat: Any) -> None:
        ops = self._ops
        match pat:
            case PlainLoadPattern():
                ops.pattern("Plain", pat.id, pat.time_series_id)
                for nl in pat.nodal_loads:
                    forces = tuple(nl.forces[i] for i in self._dof_idx)
                    ops.load(nl.node_id, *forces)
            case UniformExcitationPattern():
                args: list[Any] = [pat.direction, "-accel", pat.accel_series_id]
                if pat.vel_series_id is not None:
                    args.extend(["-vel", pat.vel_series_id])
                if pat.disp_series_id is not None:
                    args.extend(["-disp", pat.disp_series_id])
                if pat.factor != 1.0:
                    args.extend(["-fact", pat.factor])
                ops.pattern("UniformExcitation", pat.id, *args)
            case _:
                raise NotImplementedError(f"Pattern type not yet handled: {type(pat).__name__}")

    # ─────────────────────── analysis runners ───────────────────────
    def _emit_patterns_for_case(self, pattern_ids: list[int]) -> None:
        # Time series for the patterns we are about to emit.
        used_ts: set[int] = set()
        for pid in pattern_ids:
            pat = next(p for p in self.project.load_patterns if p.id == pid)
            ts_id = getattr(pat, "time_series_id", None) or getattr(pat, "accel_series_id", None)
            if ts_id is not None:
                used_ts.add(ts_id)
        for ts in self.project.time_series:
            if ts.id in used_ts:
                self._emit_time_series(ts)
        for pid in pattern_ids:
            pat = next(p for p in self.project.load_patterns if p.id == pid)
            self._emit_pattern(pat)

    def _setup_analysis(self, case: Any) -> None:
        ops = self._ops
        ops.system(case.system)
        ops.numberer("RCM")
        ops.constraints(case.constraints)
        ops.test(case.test, case.tolerance, case.max_iter)
        ops.algorithm(case.algorithm)
        if isinstance(case, StaticCase):
            ops.integrator(case.integrator, case.load_factor_increment)
        elif isinstance(case, TransientCase):
            ops.integrator(case.integrator, *case.integrator_params)
        ops.analysis("Static" if isinstance(case, StaticCase) else "Transient")

    def _run_static(self, case: StaticCase) -> StaticResults:
        ops = self._ops
        self._emit_patterns_for_case(case.pattern_ids)
        self._setup_analysis(case)

        ndf = len(self._dof_idx)
        node_disp = {n.id: np.zeros((case.n_steps, ndf)) for n in self.project.nodes}
        node_reaction = {n.id: np.zeros((case.n_steps, ndf)) for n in self.project.nodes}
        element_forces: dict[int, np.ndarray] = {}

        for step in range(case.n_steps):
            status = ops.analyze(1)
            if status != 0:
                raise RuntimeError(
                    f"Static analysis failed at step {step + 1}/{case.n_steps} "
                    f"(ops.analyze returned {status})."
                )
            ops.reactions()
            for node in self.project.nodes:
                for j, dof in enumerate(range(1, ndf + 1)):
                    node_disp[node.id][step, j] = ops.nodeDisp(node.id, dof)
                    node_reaction[node.id][step, j] = ops.nodeReaction(node.id, dof)
            for el in self.project.elements:
                # Prefer "localForce" — gives [N, V_y, V_z, T, M_y, M_z] per
                # end in the element's local frame, which is what diagrams
                # need. Fall back to global eleForce if the element type
                # doesn't expose localForce (e.g. zeroLength, truss).
                try:
                    forces = ops.eleResponse(el.id, "localForce")
                except Exception:
                    forces = []
                if not forces:
                    forces = ops.eleForce(el.id)
                if el.id not in element_forces:
                    element_forces[el.id] = np.zeros((case.n_steps, len(forces)))
                element_forces[el.id][step, :] = forces

        return StaticResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=case.n_steps,
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_forces=element_forces,
        )

    def _run_modal(self, case: ModalCase) -> ModalResults:
        """Eigenvalue analysis with automatic solver fallback.

        ARPACK (``genBandArpack``) is iterative and the OpenSees default,
        but it requires roughly ``2 * n_modes < n_free_dof`` Arnoldi
        workspace; small models cause it to abort with
        ``_saupd info = -9999``. We auto-fall back to ``-fullGenLapack``
        (a dense direct eigensolver) for small problems — slower
        asymptotically but unconditionally stable and faster in the
        small regime anyway.
        """
        ops = self._ops
        ndf = len(self._dof_idx)

        # Effective free-DOF count = total DOFs minus restrained ones.
        n_free = sum(
            ndf - sum(int(node.restraint[i]) for i in self._dof_idx)
            for node in self.project.nodes
        )
        solver = case.solver
        if solver == "genBandArpack" and 2 * case.n_modes >= n_free:
            solver = "-fullGenLapack"

        eigenvalues = np.array(ops.eigen(solver, case.n_modes), dtype=float)

        mode_shapes: dict[int, dict[int, np.ndarray]] = {}
        for mode in range(1, case.n_modes + 1):
            mode_shapes[mode] = {}
            for node in self.project.nodes:
                vec = np.array(
                    [ops.nodeEigenvector(node.id, mode, dof) for dof in range(1, ndf + 1)],
                    dtype=float,
                )
                mode_shapes[mode][node.id] = vec

        return ModalResults(
            case_id=case.id,
            case_name=case.name,
            eigenvalues=eigenvalues,
            mode_shapes=mode_shapes,
        )

    def _run_transient(self, case: TransientCase, results_dir: Path) -> TransientResults:
        import h5py

        ops = self._ops
        results_dir.mkdir(parents=True, exist_ok=True)
        recorder_dir = results_dir / "recorders"
        recorder_dir.mkdir(exist_ok=True)

        # Recorders write to text; we'll consolidate into HDF5 after.
        node_files = {
            n.id: recorder_dir / f"node_{n.id}.out" for n in self.project.nodes
        }
        for nid, path in node_files.items():
            ops.recorder(
                "Node", "-file", str(path), "-time",
                "-node", nid, "-dof", *list(range(1, len(self._dof_idx) + 1)), "disp",
            )
        elem_files = {
            el.id: recorder_dir / f"elem_{el.id}.out" for el in self.project.elements
        }
        for eid, path in elem_files.items():
            ops.recorder(
                "Element", "-file", str(path), "-time", "-ele", eid, "forces",
            )

        self._emit_patterns_for_case(case.pattern_ids)
        self._setup_analysis(case)

        status = ops.analyze(case.n_steps, case.dt)
        if status != 0:
            raise RuntimeError(
                f"Transient analysis failed (ops.analyze returned {status})."
            )

        # Flush recorders, then consolidate.
        ops.wipeAnalysis()
        ops.remove("recorders")

        h5_path = results_dir / f"case_{case.id}.h5"
        with h5py.File(h5_path, "w") as f:
            time_loaded = False
            for nid, path in node_files.items():
                if not path.exists():
                    continue
                data = np.loadtxt(path)
                if not time_loaded:
                    f.create_dataset("time", data=data[:, 0])
                    time_loaded = True
                f.create_dataset(f"nodes/{nid}/disp", data=data[:, 1:])
            for eid, path in elem_files.items():
                if not path.exists():
                    continue
                data = np.loadtxt(path)
                f.create_dataset(f"elements/{eid}/forces", data=data[:, 1:])

        return TransientResults(
            case_id=case.id,
            case_name=case.name,
            h5_path=h5_path,
            n_steps=case.n_steps,
            dt=case.dt,
        )
