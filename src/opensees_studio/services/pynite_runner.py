"""The PyNite engine: linear static and P-Delta analysis of elastic frames.

`PyNite <https://github.com/JWock82/PyNite>`_ (MIT) is a pure-Python 3D frame and
plate solver, shipped with the application as the second engine (ADR-0003). It
runs what an elastic model needs every day — a static case, with second-order
P-Delta when a member asks for it — and the results come back in exactly the
form :class:`~opensees_studio.services.opensees_runner.OpenSeesRunner` produces,
so diagrams, reactions, tables, storey shears and section cuts read them the
same way:

* nodal displacements and reactions in OpenSees' DOF order with the global sign
  (``core.plane.dof_indices`` slots; PyNite already works in global X, Y, Z);
* frame end forces as OpenSees' ``localForce``: ``[N, Vy, Vz, T, My, Mz]`` per
  end in 3D, ``[N, V, M]`` per end in 2D, in the same local axes;
* truss end forces as OpenSees reports them: the axial force first in each
  end's block, zeros elsewhere.

**Local axes.** PyNite picks a member's local y and z with rules of its own (Y is
its vertical) plus a roll angle about the member. Each member gets the roll that
lines its axes up with OpenSees' (:func:`core.geometry.local_axes
.frame_local_axes`; in 2D, OpenSees' plane is X-Z with its z along -Y), and the
alignment is checked after building: a mismatch is an error, not a silently
swapped Iy / Iz.

**What it refuses**, each with a message (the analysis then needs OpenSeesPy):
anything but elastic frames on an :class:`ElasticSection` (Euler-Bernoulli,
no shear areas) and trusses on an :class:`ElasticUniaxial`; shells; zero-length
elements, bearings and links; constraints, rigid links and diaphragms; partial
fixity springs, end offsets and insertion points; surface, temperature and
imposed-displacement loads; time series other than Linear and Constant;
integrators other than LoadControl; corotational members; and a joint lying
inside a member without being connected to it (PyNite would connect it).

Linear runs superpose: every pattern is a PyNite load case solved once, and
each analysis step is a load combination scaled by the pattern's time series at
that step's load factor. P-Delta solves each step's combination on its own.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import numpy as np

from opensees_studio.core.analysis import StaticCase
from opensees_studio.core.area_loads import pattern_distributed_loads
from opensees_studio.core.connectivity import joints_on_bars
from opensees_studio.core.duplicates import default_tolerance
from opensees_studio.core.geometry.elements import (
    FRAME_ELEMENT_CLASSES,
    CorotTrussElement,
    TrussElement,
)
from opensees_studio.core.geometry.local_axes import frame_local_axes
from opensees_studio.core.loads import ConstantTimeSeries, LinearTimeSeries, PlainLoadPattern
from opensees_studio.core.materials import ElasticUniaxial
from opensees_studio.core.plane import dof_indices
from opensees_studio.core.project import Project
from opensees_studio.core.sections import ElasticSection
from opensees_studio.core.self_weight import nodal_self_weight_loads, self_weight_loads
from opensees_studio.services.results import StaticResults

#: PyNite's global DOF names, in the 6-slot order of a node's storage.
_GLOBAL = ("DX", "DY", "DZ", "RX", "RY", "RZ")
_REACTION = ("RxnFX", "RxnFY", "RxnFZ", "RxnMX", "RxnMY", "RxnMZ")
_FORCE = ("FX", "FY", "FZ", "MX", "MY", "MZ")

#: Alignment of PyNite's local axes with OpenSees' must hold to this.
AXIS_TOLERANCE = 1e-9

#: Bending properties a truss bar is given: irrelevant, every rotation is released.
_TRUSS_INERTIA = 1e-6


class PyNiteUnsupportedError(ValueError):
    """The model uses something PyNite does not model; the message says what."""


def _node(node_id: int) -> str:
    return f"N{node_id}"


def _member(element_id: int) -> str:
    return f"M{element_id}"


def _case(pattern_id: int) -> str:
    return f"P{pattern_id}"


def _combo(step: int) -> str:
    return f"S{step}"


def _solver_axes(project: Project, element: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OpenSees' local (x, y, z) of a two-node member, in global coordinates."""
    coords = {n.id: n.coords for n in project.nodes}
    i, j = element.nodes
    if project.ndm == 3:
        axes = frame_local_axes(3, coords[i], coords[j])
        if axes is None:
            raise PyNiteUnsupportedError(f"Element {element.id} has no length.")
        return axes
    # 2D: OpenSees works in the X-Z plane with its z along -Y; local y is x
    # turned +90 degrees about that z.
    pi, pj = np.asarray(coords[i], float), np.asarray(coords[j], float)
    axis = pj - pi
    length = float(np.linalg.norm(axis))
    if length == 0.0:
        raise PyNiteUnsupportedError(f"Element {element.id} has no length.")
    x = axis / length
    z = np.array([0.0, -1.0, 0.0])
    return x, np.cross(z, x), z


def _roll(model: Any, name: str, target_y: np.ndarray) -> float:
    """The roll (degrees) that turns PyNite's local y of ``name`` onto ``target_y``."""
    member = model.members[name]
    member.rotation = 0.0
    x, y0 = member.T()[0, :3], member.T()[1, :3]
    return math.degrees(math.atan2(float(np.cross(y0, target_y) @ x), float(y0 @ target_y)))


class PyNiteRunner:
    """Builds a PyNite model from a project and runs a :class:`StaticCase` on it."""

    def __init__(
        self, project: Project, on_progress: Callable[[int, int], None] | None = None
    ) -> None:
        self.project = project
        self._on_progress = on_progress
        self._slots = dof_indices(project.ndm, project.ndf)
        self._axes: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    # ── entry point ──────────────────────────────────────────────────
    def run(self, case: Any, results_dir: Any = None) -> StaticResults:
        if not isinstance(case, StaticCase):
            raise PyNiteUnsupportedError(f"PyNite runs static cases; '{case.name}' is {case.type}.")
        if case.integrator != "LoadControl":
            raise PyNiteUnsupportedError(
                f"PyNite runs load-controlled static cases; '{case.name}' uses {case.integrator}."
            )
        model = self._build(case)
        steps = range(1, case.n_steps + 1)
        for step in steps:
            factors = self._step_factors(case, step)
            model.add_load_combo(_combo(step), factors or {"__none__": 0.0})
        pdelta = any(
            getattr(el, "geom_transf", "Linear") == "PDelta" for el in self.project.elements
        )
        if pdelta:
            model.analyze_PDelta(log=False, check_stability=True)
        else:
            model.analyze_linear(log=False, check_stability=True)
        return self._results(case, model)

    # ── the model ────────────────────────────────────────────────────
    def _refuse_what_pynite_lacks(self) -> None:
        project = self.project
        problems: list[str] = []
        element: Any
        if project.mp_constraints or project.rigid_links or project.diaphragms:
            problems.append("equalDOF constraints, rigid links and diaphragms")
        for element in project.elements:
            if not isinstance(element, (*FRAME_ELEMENT_CLASSES, TrussElement, CorotTrussElement)):
                problems.append(f"{element.type} elements (element {element.id})")
            elif isinstance(element, FRAME_ELEMENT_CLASSES):
                if getattr(element, "geom_transf", "Linear") == "Corotational":
                    problems.append(f"corotational members (element {element.id})")
                if not element.end_offsets.is_default() or not element.insertion.is_default():
                    problems.append(f"end offsets and insertion points (element {element.id})")
                for end in ("i", "j"):
                    if element.releases.end(end).springs:
                        problems.append(f"partial-fixity releases (element {element.id})")
        if problems:
            unique = list(dict.fromkeys(problems))
            raise PyNiteUnsupportedError(
                "PyNite does not model "
                + "; ".join(unique[:5])
                + (" …" if len(unique) > 5 else "")
                + ". Run this model with OpenSeesPy (Options → Solver)."
            )
        inside = joints_on_bars(project, default_tolerance(project))
        if inside:
            element_id, node_id = inside[0]
            raise PyNiteUnsupportedError(
                f"Joint {node_id} lies inside member {element_id} without being connected to "
                "it; PyNite would connect it. Use Edit → Divide Frames at Joints, or OpenSeesPy."
            )

    def _section(self, element: Any) -> ElasticSection:
        section = next((s for s in self.project.sections if s.id == element.section_id), None)
        if not isinstance(section, ElasticSection):
            raise PyNiteUnsupportedError(
                f"Element {element.id} needs an elastic section for PyNite "
                f"(it has {type(section).__name__}). Run it with OpenSeesPy."
            )
        if section.has_shear_deformation:
            raise PyNiteUnsupportedError(
                f"Section {section.id} has shear areas (a Timoshenko beam); PyNite is "
                "Euler-Bernoulli. Run it with OpenSeesPy."
            )
        if self.project.ndm == 3 and (section.Iy is None or section.G is None or section.J is None):
            raise PyNiteUnsupportedError(f"Section {section.id} needs Iy, G and J in 3D.")
        return section

    def _build(self, case: StaticCase) -> Any:
        from Pynite import FEModel3D

        self._refuse_what_pynite_lacks()
        project = self.project
        model = FEModel3D()
        for node in project.nodes:
            model.add_node(_node(node.id), *map(float, node.coords))
            fixed = list(node.restraint)
            for slot in range(6):
                if slot not in self._slots:
                    fixed[slot] = True  # a DOF the model does not have
            model.def_support(_node(node.id), *fixed)
            for slot, k in enumerate(getattr(node, "spring", (0.0,) * 6)):
                if k and slot in self._slots:
                    model.def_support_spring(_node(node.id), _GLOBAL[slot], float(k))

        element: Any
        for element in project.elements:
            name = _member(element.id)
            i, j = (_node(n) for n in element.nodes)
            if isinstance(element, (TrussElement, CorotTrussElement)):
                material = next((m for m in project.materials if m.id == element.material_id), None)
                if not isinstance(material, ElasticUniaxial):
                    raise PyNiteUnsupportedError(
                        f"Truss {element.id} needs an elastic material for PyNite "
                        f"(it has {type(material).__name__}). Run it with OpenSeesPy."
                    )
                model.add_material(f"T{element.id}", material.E, material.E / 2.6, 0.3, 0.0)
                model.add_section(
                    f"T{element.id}", element.area, _TRUSS_INERTIA, _TRUSS_INERTIA, _TRUSS_INERTIA
                )
                model.add_member(name, i, j, f"T{element.id}", f"T{element.id}")
                model.def_releases(name, Rxi=True, Ryi=True, Rzi=True, Ryj=True, Rzj=True)
            else:
                section = self._section(element)
                mods = element.modifiers
                g = section.G if section.G is not None else section.E / 2.6
                model.add_material(f"E{element.id}", section.E, g, section.E / (2 * g) - 1, 0.0)
                model.add_section(
                    f"E{element.id}",
                    section.A * mods.area,
                    (section.Iy if section.Iy is not None else section.Iz) * mods.i22,
                    section.Iz * mods.i33,
                    (section.J if section.J is not None else section.Iz) * mods.torsion,
                )
                model.add_member(name, i, j, f"E{element.id}", f"E{element.id}")
                flags = {}
                for end in ("i", "j"):
                    released = element.releases.end(end).released
                    flags[f"Rx{end}"] = "T" in released
                    flags[f"Ry{end}"] = "M2" in released
                    flags[f"Rz{end}"] = "M3" in released
                if any(flags.values()):
                    model.def_releases(name, **flags)
            axes = _solver_axes(project, element)
            self._axes[element.id] = axes
            model.members[name].rotation = _roll(model, name, axes[1])

        for name, (eid, axes) in zip(
            [_member(e) for e in self._axes], self._axes.items(), strict=True
        ):
            transform = model.members[name].T()
            if not (
                np.allclose(transform[1, :3], axes[1], atol=AXIS_TOLERANCE)
                and np.allclose(transform[2, :3], axes[2], atol=AXIS_TOLERANCE)
            ):
                raise RuntimeError(f"PyNite's local axes of element {eid} do not match OpenSees'.")

        for pattern_id in case.pattern_ids:
            pattern = next((p for p in project.load_patterns if p.id == pattern_id), None)
            if not isinstance(pattern, PlainLoadPattern):
                raise PyNiteUnsupportedError(
                    f"PyNite runs plain load patterns; pattern {pattern_id} is not one."
                )
            self._add_loads(model, pattern)
        return model

    def _add_loads(self, model: Any, pattern: PlainLoadPattern) -> None:
        project = self.project
        name = _case(pattern.id)
        for kind in ("surface_loads", "imposed_displacements", "temperature_loads"):
            if getattr(pattern, kind):
                raise PyNiteUnsupportedError(
                    f"Pattern {pattern.id} has {kind.replace('_', ' ')}, which the PyNite engine "
                    "does not apply yet. Run it with OpenSeesPy."
                )
        for nodal in pattern.nodal_loads:
            for slot, value in enumerate(nodal.forces):
                if value and slot in self._slots:
                    model.add_node_load(_node(nodal.node_id), _FORCE[slot], float(value), name)
        lengths = {e.id: model.members[_member(e.id)].L() for e in project.elements}
        uniform = [*pattern.element_loads, *self_weight_loads(project, pattern.self_weight)]
        for ul in uniform:
            member = _member(ul.element_id)
            for direction, w in (("Fx", ul.wx), ("Fy", ul.wy), ("Fz", ul.wz)):
                if w:
                    model.add_member_dist_load(member, direction, float(w), float(w), case=name)
        for tl in pattern_distributed_loads(project, pattern):
            member = _member(tl.element_id)
            length = lengths[tl.element_id]
            x1, x2 = tl.x_start * length, tl.x_end * length
            for direction, w1, w2 in (
                ("Fx", tl.wx_start, tl.wx_end),
                ("Fy", tl.wy_start, tl.wy_end),
                ("Fz", tl.wz_start, tl.wz_end),
            ):
                if w1 or w2:
                    model.add_member_dist_load(member, direction, w1, w2, x1, x2, case=name)
        for pl in pattern.point_loads:
            member = _member(pl.element_id)
            x = pl.x * lengths[pl.element_id]
            for direction, p in (("Fx", pl.px), ("Fy", pl.py), ("Fz", pl.pz)):
                if p:
                    model.add_member_pt_load(member, direction, float(p), x, name)
        for node_id, force in nodal_self_weight_loads(project, pattern.self_weight).items():
            for slot, value in enumerate(force):
                if value and slot in self._slots:
                    model.add_node_load(_node(node_id), _FORCE[slot], float(value), name)

    def _step_factors(self, case: StaticCase, step: int) -> dict[str, float]:
        """Each pattern's scale at a step: its time series at the step's load factor."""
        series = {ts.id: ts for ts in self.project.time_series}
        load_factor = step * case.load_factor_increment
        factors: dict[str, float] = {}
        for pattern_id in case.pattern_ids:
            pattern = next(p for p in self.project.load_patterns if p.id == pattern_id)
            assert isinstance(pattern, PlainLoadPattern)  # _build refused anything else
            ts = series.get(pattern.time_series_id)
            if isinstance(ts, LinearTimeSeries):
                factors[_case(pattern_id)] = ts.factor * load_factor
            elif isinstance(ts, ConstantTimeSeries):
                factors[_case(pattern_id)] = ts.factor
            else:
                raise PyNiteUnsupportedError(
                    f"Pattern {pattern_id} uses a {type(ts).__name__}; PyNite runs Linear and "
                    "Constant time series in a static case."
                )
        return factors

    # ── the results, in OpenSees' layout ─────────────────────────────
    def _results(self, case: StaticCase, model: Any) -> StaticResults:
        project = self.project
        slots = self._slots
        n = case.n_steps
        ndf = len(slots)
        node_disp = {node.id: np.zeros((n, ndf)) for node in project.nodes}
        node_reaction = {node.id: np.zeros((n, ndf)) for node in project.nodes}
        element_forces: dict[int, np.ndarray] = {}
        for k in range(n):
            combo = _combo(k + 1)
            for node in project.nodes:
                pn = model.nodes[_node(node.id)]
                for j, slot in enumerate(slots):
                    node_disp[node.id][k, j] = getattr(pn, _GLOBAL[slot]).get(combo, 0.0)
                    node_reaction[node.id][k, j] = getattr(pn, _REACTION[slot]).get(combo, 0.0)
            for element in project.elements:
                local = np.asarray(model.members[_member(element.id)].f(combo), float).ravel()
                vector = self._local_force(element, local)
                if element.id not in element_forces:
                    element_forces[element.id] = np.zeros((n, vector.size))
                element_forces[element.id][k, :] = vector
            if self._on_progress is not None:
                self._on_progress(k + 1, n)
        return StaticResults(
            case_id=case.id,
            case_name=case.name,
            n_steps=n,
            node_disp=node_disp,
            node_reaction=node_reaction,
            element_forces=element_forces,
        )

    def _local_force(self, element: Any, local: np.ndarray) -> np.ndarray:
        """PyNite's 12 local end forces as OpenSees' ``localForce`` of this element."""
        ndm, ndf = self.project.ndm, self.project.ndf
        if isinstance(element, (TrussElement, CorotTrussElement)):
            out = np.zeros(2 * ndf)
            out[0], out[ndf] = local[0], local[6]
            return out
        if ndm == 2:
            return local[[0, 1, 5, 6, 7, 11]]
        return local
