"""Subdivide frame members that use a :class:`NonprismaticSection`.

A nonprismatic section is a library template made of prismatic elastic
sections.  OpenSees has no linear tapered frame element, so the modeler
materialises the template as a chain of ordinary ``elasticBeamColumn``
elements: the member is split into ``subdivisions`` equal pieces and each
piece gets the elastic section interpolated at its midpoint.  The original
frame's loads are split across the pieces too.

The template (and the prismatic sections it refers to) stays in
``project.sections`` so the Section Library can keep editing it, but no
element references it after materialisation.

The module is import-only: the importer calls :func:`materialize_nonprismatic`
after building the load patterns, and the GUI assignment command calls it when
a nonprismatic section is assigned to a selection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    Group,
    Node,
    NonprismaticSection,
    PipeShape,
    PlainLoadPattern,
    PointElementLoad,
    RectShape,
    TemperatureLoad,
    TrapezoidalElementLoad,
    TubeShape,
    UniformElementLoad,
    WideFlangeShape,
)
from opensees_studio.core.geometry.frame_options import (
    EndRelease,
    FrameEndOffsets,
    FrameReleases,
)

if TYPE_CHECKING:
    from opensees_studio.core import Project

_VARIATION_EXPONENT = {"linear": 1.0, "parabolic": 2.0, "cubic": 3.0}
_EPS = 1e-12

NONPRISMATIC_GROUP_PREFIX = "Nonprismatic section"
"""Name prefix of the group that remembers one subdivided member.

The group lets the Section Library find the pieces again after the template is
edited and refresh their section properties without touching the topology.
"""


def _taper_group_name(template_id: int, member_id: int) -> str:
    return f"{NONPRISMATIC_GROUP_PREFIX} {template_id} member {member_id}"


@dataclass
class MaterializationReport:
    """What :func:`materialize_nonprismatic` changed in the project."""

    members: int = 0
    elements: int = 0
    nodes: int = 0
    sections: int = 0
    subdivisions: dict[int, int] = field(default_factory=dict)
    """Template section id -> number of pieces used by the first member of it."""

    def merge(self, other: MaterializationReport) -> None:
        self.members += other.members
        self.elements += other.elements
        self.nodes += other.nodes
        self.sections += other.sections
        self.subdivisions.update(other.subdivisions)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _variation(value: str, u: float) -> float:
    return float(_clamp01(u) ** _VARIATION_EXPONENT.get(value, 1.0))


def _interp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def _interp_optional(a: float | None, b: float | None, f: float) -> float | None:
    if a is None and b is None:
        return None
    if a is None:
        return b
    if b is None:
        return a
    return _interp(a, b, f)


def _shape_properties(shape: Any, ndm: int = 3) -> dict[str, float] | None:
    """A, Iz, Iy, J, As2, As3 of a drawing hint, in the project's local axes.

    The shape's ``d`` is the SAP2000 depth: local z in a 3D model, local y in a
    2D one (where the model bends in the X-Z plane).  ``Iz`` is the in-plane
    inertia in 2D; in 3D ``Iz`` is the weak axis and ``Iy`` the strong one for
    the rectangular-depth shapes.
    """
    if isinstance(shape, RectShape):
        d, b = shape.d, shape.b
        long, short = max(d, b), min(d, b)
        j = long * short**3 * (1 / 3 - 0.21 * short / long * (1 - short**4 / (12 * long**4)))
        return {
            "A": d * b,
            "Iz": b * d**3 / 12 if ndm == 2 else d * b**3 / 12,
            "Iy": d * b**3 / 12 if ndm == 2 else b * d**3 / 12,
            "J": j,
            "As2": 5 / 6 * d * b,
            "As3": 5 / 6 * d * b,
        }
    if isinstance(shape, PipeShape):
        r_o, r_i = shape.od / 2, shape.od / 2 - shape.t
        if r_i <= 0:
            return None
        i = math.pi / 4 * (r_o**4 - r_i**4)
        a = math.pi * (r_o**2 - r_i**2)
        return {"A": a, "Iz": i, "Iy": i, "J": 2 * i, "As2": a / 2, "As3": a / 2}
    if isinstance(shape, TubeShape):
        d, b, t = shape.d, shape.b, shape.t
        if d <= 2 * t or b <= 2 * t:
            return None
        a = d * b - (d - 2 * t) * (b - 2 * t)
        iz = (d * b**3 - (d - 2 * t) * (b - 2 * t) ** 3) / 12
        iy = (b * d**3 - (b - 2 * t) * (d - 2 * t) ** 3) / 12
        return {
            "A": a,
            "Iz": iy if ndm == 2 else iz,
            "Iy": iz if ndm == 2 else iy,
            "J": 4 * ((d - t) * (b - t)) ** 2 / (2 * (d - t) / t + 2 * (b - t) / t),
            "As2": 2 * d * t,
            "As3": 2 * b * t,
        }
    if isinstance(shape, WideFlangeShape):
        d, bf, tw, tf = shape.d, shape.bf, shape.tw, shape.tf
        hw = d - 2 * tf
        if hw <= 0:
            return None
        iz = (2 * tf * bf**3 + hw * tw**3) / 12
        iy = (bf * d**3 - (bf - tw) * hw**3) / 12
        return {
            "A": 2 * bf * tf + hw * tw,
            "Iz": iy if ndm == 2 else iz,
            "Iy": iz if ndm == 2 else iy,
            "J": (2 * bf * tf**3 + (d - tf) * tw**3) / 3,
            "As2": d * tw,
            "As3": 5 / 3 * bf * tf,
        }
    return None


def _shape_matches(shape: Any, section: ElasticSection, ndm: int = 3) -> bool:
    """The drawn shape and the section's A/Iz/Iy agree (it is not a generic hint).

    A 2D section has no ``Iy``; the out-of-plane property is not used by the
    analysis, so only ``A`` and ``Iz`` are compared there.
    """
    props = _shape_properties(shape, ndm)
    if props is None:
        return False
    for key in ("A", "Iz", "Iy"):
        value = getattr(section, key)
        if value is None:
            if key == "Iy":
                continue
            return False
        if abs(props[key] - value) > 1e-6 + 0.02 * abs(value):
            return False
    return True


def _interp_shape(start: Any, end: Any, f: float) -> Any:
    """Interpolate two shape hints of the same kind, for the extruded view only."""
    if start is None or end is None or start.kind != end.kind:
        return start if start is not None else end
    values: dict[str, float] = {}
    for name in type(start).model_fields:
        if name == "kind":
            continue
        a = getattr(start, name)
        b = getattr(end, name)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            values[name] = _interp(float(a), float(b), f)
    try:
        return type(start)(**values)
    except (TypeError, ValueError):
        return start


def section_at(project: Project, section: NonprismaticSection, t: float) -> ElasticSection:
    """The elastic section of ``section`` at relative position ``t`` (0 = end i).

    Properties vary with the segment's ``variation`` (linear, parabolic or
    cubic); the elastic modulus, shear modulus and unit weight vary linearly.
    A shape hint is interpolated when both ends use the same shape kind, so a
    subdivided member still draws as a taper.
    """
    t = _clamp01(t)
    fractions = section.fractions()
    by_id = {s.id: s for s in project.sections}
    accumulator = 0.0
    start: ElasticSection | None = None
    end: ElasticSection | None = None
    u = 0.0
    variation = "linear"
    for index, (segment, length) in enumerate(zip(section.segments, fractions, strict=True)):
        if t <= accumulator + length + _EPS or index == len(section.segments) - 1:
            s = by_id.get(segment.start_section_id)
            e = by_id.get(segment.end_section_id)
            if not isinstance(s, ElasticSection) or not isinstance(e, ElasticSection):
                raise ValueError(
                    f"Nonprismatic section {section.id}: every segment must reference an "
                    "ElasticSection."
                )
            start, end = s, e
            u = 0.0 if length <= 0.0 else _clamp01((t - accumulator) / length)
            variation = segment.variation
            break
        accumulator += length
    if start is None or end is None:
        raise ValueError(f"Nonprismatic section {section.id} has no segments.")
    f = _variation(variation, u)
    linear = u
    shape = _interp_shape(start.shape, end.shape, f)
    values = {
        # The material properties do not follow the section-depth curve.
        "E": _interp(start.E, end.E, linear),
        "G": _interp_optional(start.G, end.G, linear),
        "unit_weight": _interp(start.unit_weight, end.unit_weight, linear),
        # A, Iz and Iy follow the section geometry when both ends describe a
        # real shape (a rectangular depth taper, for example).  Otherwise fall
        # back to interpolating the properties directly.
        "A": _interp(start.A, end.A, f),
        "Iz": _interp(start.Iz, end.Iz, f),
        "Iy": _interp_optional(start.Iy, end.Iy, f),
        "J": _interp_optional(start.J, end.J, f),
        "As2": _interp_optional(start.As2, end.As2, f),
        "As3": _interp_optional(start.As3, end.As3, f),
        "shape": shape,
    }
    same_properties = all(
        math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-15)
        for a, b in (
            (start.A, end.A),
            (start.Iz, end.Iz),
            (start.Iy or 0.0, end.Iy or 0.0),
        )
    )
    if (
        not same_properties
        and start.shape is not None
        and end.shape is not None
        and start.shape.kind == end.shape.kind
        and _shape_matches(start.shape, start, project.ndm)
        and _shape_matches(end.shape, end, project.ndm)
    ):
        props = _shape_properties(shape, project.ndm)
        if props is not None:
            values["A"] = props["A"]
            values["Iz"] = props["Iz"]
            if start.Iy is not None:
                values["Iy"] = props["Iy"]
    return ElasticSection(
        id=1,
        name=f"{section.name or 'Nonprismatic'} @ {t:g}",
        **values,
    )


def _has_non_uniform_element_load(project: Project, element_id: int) -> bool:
    """A point, partial or varying frame load, which a Timoshenko piece cannot take.

    The runner restricts ``ElasticTimoshenkoBeam`` to full-length uniform loads
    (and self weight).  A tapered member that had shear areas at its template
    must therefore fall back to Euler-Bernoulli when one of its load patterns
    carries anything else; otherwise the split pieces would be refused at run
    time.  The SAP2000 importer makes the same decision before it builds the
    template.
    """
    for pattern in project.load_patterns:
        if not isinstance(pattern, PlainLoadPattern):
            continue
        if any(load.element_id == element_id for load in pattern.point_loads):
            return True
        for load in pattern.distributed_loads:
            if load.element_id != element_id:
                continue
            if (
                abs(load.x_start) > _EPS
                or abs(load.x_end - 1.0) > _EPS
                or not math.isclose(load.wy_start, load.wy_end)
                or not math.isclose(load.wz_start, load.wz_end)
                or not math.isclose(load.wx_start, load.wx_end)
            ):
                return True
    return False


def _section_key(section: ElasticSection) -> tuple[Any, ...]:
    return (
        round(section.E, 9),
        round(section.A, 12),
        round(section.Iz, 12),
        None if section.Iy is None else round(section.Iy, 12),
        None if section.G is None else round(section.G, 9),
        None if section.J is None else round(section.J, 12),
        None if section.As2 is None else round(section.As2, 12),
        None if section.As3 is None else round(section.As3, 12),
        round(section.unit_weight, 9),
        None if section.shape is None else section.shape.model_dump_json(),
    )


def _load_zones(pattern: PlainLoadPattern, element_id: int, count: int, sub_ids: list[int]) -> None:
    """Split the element loads of one frame across its ``count`` pieces."""
    if not any(
        load.element_id == element_id
        for load in (
            pattern.element_loads
            + pattern.point_loads
            + pattern.distributed_loads
            + pattern.temperature_loads
        )
    ):
        return

    # Full-length uniform loads: the intensity is per unit length, so every
    # piece gets the same value.
    uniform: list[UniformElementLoad] = []
    for uniform_load in pattern.element_loads:
        if uniform_load.element_id == element_id:
            uniform.extend(
                UniformElementLoad(
                    element_id=sub_id,
                    wx=uniform_load.wx,
                    wy=uniform_load.wy,
                    wz=uniform_load.wz,
                )
                for sub_id in sub_ids
            )
        else:
            uniform.append(uniform_load)
    pattern.element_loads = uniform

    # Point loads: find the piece that contains x and keep its relative offset
    # inside that piece.
    points: list[PointElementLoad] = []
    for point_load in pattern.point_loads:
        if point_load.element_id != element_id:
            points.append(point_load)
            continue
        k = min(int(point_load.x * count), count - 1)
        local = _clamp01(point_load.x * count - k)
        points.append(
            PointElementLoad(
                element_id=sub_ids[k],
                px=point_load.px,
                py=point_load.py,
                pz=point_load.pz,
                x=local,
            )
        )
    pattern.point_loads = points

    # Trapezoidal loads: intersect the loaded interval with every piece and
    # interpolate the intensity at the overlap ends.
    distributed: list[TrapezoidalElementLoad] = []
    for distributed_load in pattern.distributed_loads:
        if distributed_load.element_id != element_id:
            distributed.append(distributed_load)
            continue
        x0, x1 = distributed_load.x_start, distributed_load.x_end
        wy0, wy1 = distributed_load.wy_start, distributed_load.wy_end
        wz0, wz1 = distributed_load.wz_start, distributed_load.wz_end
        wx0, wx1 = distributed_load.wx_start, distributed_load.wx_end
        if x1 < x0:
            x0, x1 = x1, x0
            wy0, wy1 = wy1, wy0
            wz0, wz1 = wz1, wz0
            wx0, wx1 = wx1, wx0
        span = x1 - x0
        if span <= _EPS:
            k = min(int(x0 * count), count - 1)
            local = _clamp01(x0 * count - k)
            distributed.append(
                TrapezoidalElementLoad(
                    element_id=sub_ids[k],
                    x_start=local,
                    x_end=local,
                    wy_start=wy0,
                    wy_end=wy1,
                    wz_start=wz0,
                    wz_end=wz1,
                    wx_start=wx0,
                    wx_end=wx1,
                )
            )
            continue

        def value(start: float, end: float, x: float, x0: float = x0, span: float = span) -> float:
            return start + (end - start) * ((x - x0) / span)

        for k, sub_id in enumerate(sub_ids):
            a = max(x0, k / count)
            b = min(x1, (k + 1) / count)
            if b - a <= _EPS:
                continue
            distributed.append(
                TrapezoidalElementLoad(
                    element_id=sub_id,
                    x_start=_clamp01(a * count - k),
                    x_end=_clamp01(b * count - k),
                    wy_start=value(wy0, wy1, a),
                    wy_end=value(wy0, wy1, b),
                    wz_start=value(wz0, wz1, a),
                    wz_end=value(wz0, wz1, b),
                    wx_start=value(wx0, wx1, a),
                    wx_end=value(wx0, wx1, b),
                )
            )
    pattern.distributed_loads = distributed

    # A temperature change applies to the whole member; every piece sees the
    # same uniform change and gradient.
    temperatures: list[TemperatureLoad] = []
    for temperature_load in pattern.temperature_loads:
        if temperature_load.element_id != element_id:
            temperatures.append(temperature_load)
            continue
        temperatures.extend(
            TemperatureLoad(
                element_id=sub_id,
                alpha=temperature_load.alpha,
                uniform=temperature_load.uniform,
                gradient_y=temperature_load.gradient_y,
                gradient_z=temperature_load.gradient_z,
            )
            for sub_id in sub_ids
        )
    pattern.temperature_loads = temperatures


def _replace_groups(project: Project, element_id: int, sub_ids: list[int]) -> None:
    for group in project.groups:
        if element_id not in group.element_ids:
            continue
        index = group.element_ids.index(element_id)
        group.element_ids[index : index + 1] = sub_ids


def materialize_nonprismatic(
    project: Project,
    *,
    element_ids: set[int] | None = None,
    subdivisions: int | None = None,
) -> MaterializationReport:
    """Split every elastic frame that uses a nonprismatic section.

    ``element_ids`` limits the work to a selection (the GUI uses it);
    ``subdivisions`` overrides the template value for this call.  The original
    element id is kept for the first piece, so an existing single-element
    reference stays meaningful; the remaining pieces get new ids.

    Raises:
        ValueError: if a target is not an ``ElasticBeamColumn`` or a template
            refers to a section that is not an ``ElasticSection``.
    """
    templates = {s.id: s for s in project.sections if isinstance(s, NonprismaticSection)}
    if not templates:
        return MaterializationReport()

    bad = [
        el.id
        for el in project.elements
        if getattr(el, "section_id", None) in templates
        and not isinstance(el, ElasticBeamColumn)
        and (element_ids is None or el.id in element_ids)
    ]
    if bad:
        raise ValueError(
            "A nonprismatic section can only be assigned to ElasticBeamColumn elements; "
            f"element(s) {', '.join(map(str, bad))} are a different frame type."
        )

    targets = [
        el
        for el in project.elements
        if isinstance(el, ElasticBeamColumn)
        and el.section_id in templates
        and (element_ids is None or el.id in element_ids)
    ]
    if not targets:
        return MaterializationReport()

    report = MaterializationReport()
    node_by_id = {n.id: n for n in project.nodes}
    next_node = max((n.id for n in project.nodes), default=0) + 1
    next_element = max((el.id for el in project.elements), default=0) + 1
    next_section = max((s.id for s in project.sections), default=0) + 1
    section_by_key: dict[tuple[Any, ...], ElasticSection] = {}
    for section in project.sections:
        if isinstance(section, ElasticSection):
            section_by_key.setdefault(_section_key(section), section)

    # Work on a copy of the list so the original order is preserved when the
    # first piece replaces the frame.
    elements = list(project.elements)
    for target in targets:
        template = templates[target.section_id]
        count = subdivisions if subdivisions is not None else template.subdivisions
        if count < 12:
            count = 12
        count = max(12, min(200, int(count)))
        node_i = node_by_id.get(target.nodes[0])
        node_j = node_by_id.get(target.nodes[1])
        if node_i is None or node_j is None:
            raise ValueError(f"Element {target.id} refers to a missing node.")
        p_i = node_i.coords
        p_j = node_j.coords

        start_section = section_at(project, template, 0.0)
        a_ref = start_section.A if start_section.A > 0.0 else None
        drop_shear = _has_non_uniform_element_load(project, target.id)

        pieces = []
        for k in range(count):
            t = (k + 0.5) / count
            section = section_at(project, template, t)
            if drop_shear and (section.As2 is not None or section.As3 is not None):
                section = section.model_copy(update={"As2": None, "As3": None})
            key = _section_key(section)
            existing = section_by_key.get(key)
            if existing is None:
                sid = next_section
                next_section += 1
                existing = section.model_copy(
                    update={
                        "id": sid,
                        "name": f"{template.name or 'Nonprismatic'} [{k + 1}/{count}]",
                    }
                )
                project.sections.append(existing)
                section_by_key[key] = existing
                report.sections += 1
            pieces.append((k, existing))

        # Interior joints.
        interior: list[int] = [target.nodes[0]]
        for k in range(1, count):
            fraction = k / count
            coords = tuple(
                float(a) + (float(b) - float(a)) * fraction for a, b in zip(p_i, p_j, strict=True)
            )
            node = Node(id=next_node, coords=coords)  # type: ignore[arg-type]
            next_node += 1
            project.nodes.append(node)
            interior.append(node.id)
            report.nodes += 1
        interior.append(target.nodes[1])

        new_elements: list[ElasticBeamColumn] = []
        for k, section in pieces:
            eid = target.id if k == 0 else next_element
            if k > 0:
                next_element += 1
            if k == 0 and count > 1:
                # The j end of the first piece is an interior joint: only the
                # true member end keeps the assignment.
                releases = target.releases.model_copy(update={"j": EndRelease()})
            elif k == count - 1:
                releases = target.releases.model_copy(update={"i": EndRelease()})
            else:
                releases = FrameReleases()
            offsets = target.end_offsets
            if k not in (0, count - 1):
                offsets = FrameEndOffsets()
            elif k == 0:
                offsets = offsets.model_copy(update={"length_j": 0.0})
            elif k == count - 1:
                offsets = offsets.model_copy(update={"length_i": 0.0})
            rho = target.rho
            if a_ref is not None:
                rho = target.rho * (section.A / a_ref)
            new_elements.append(
                target.model_copy(
                    update={
                        "id": eid,
                        "nodes": (interior[k], interior[k + 1]),
                        "section_id": section.id,
                        "rho": max(0.0, rho),
                        "releases": releases,
                        "end_offsets": offsets,
                    }
                )
            )

        index = next(i for i, el in enumerate(elements) if el.id == target.id)
        elements[index : index + 1] = new_elements
        sub_ids = [el.id for el in new_elements]
        for pattern in project.load_patterns:
            if isinstance(pattern, PlainLoadPattern):
                _load_zones(pattern, target.id, count, sub_ids)
        _replace_groups(project, target.id, sub_ids)
        group_name = _taper_group_name(template.id, target.id)
        group = next((g for g in project.groups if g.name == group_name), None)
        if group is None:
            group = Group(
                id=project.next_group_id(),
                name=group_name,
                element_ids=sub_ids,
                colour="#e6194b",
            )
            project.groups.append(group)
        else:
            group.element_ids = sorted(set(group.element_ids) | set(sub_ids))

        report.members += 1
        report.elements += count
        report.subdivisions[template.id] = count

    project.elements[:] = elements
    return report


def _group_member_ids(project: Project, template_id: int) -> list[list[int]]:
    prefix = f"{NONPRISMATIC_GROUP_PREFIX} {template_id} member "
    return [
        list(group.element_ids)
        for group in project.groups
        if group.name.startswith(prefix) and group.element_ids
    ]


@dataclass
class RefreshReport:
    """What :func:`refresh_nonprismatic` changed."""

    members: int = 0
    elements: int = 0
    stale_counts: int = 0
    """Members whose piece count differs from the template's ``subdivisions``."""


def refresh_nonprismatic(project: Project, section: NonprismaticSection) -> RefreshReport:
    """Re-interpolate the pieces of members already built from ``section``.

    The Section Library calls this after a nonprismatic template is edited.
    The topology (number of pieces and the loads split across them) is kept;
    only the section properties (and the mass per length that follows them)
    are refreshed.  If the template's subdivision count changed, the existing
    members keep their old piece count and are counted in
    ``RefreshReport.stale_counts`` so the caller can ask the user to reassign
    the section.
    """
    report = RefreshReport()
    section_by_key: dict[tuple[Any, ...], ElasticSection] = {}
    sections_by_id = {s.id: s for s in project.sections}
    for existing_section in project.sections:
        if isinstance(existing_section, ElasticSection):
            section_by_key.setdefault(_section_key(existing_section), existing_section)
    elements = list(project.elements)
    elements_by_id = {el.id: i for i, el in enumerate(elements)}
    next_section = max((s.id for s in project.sections), default=0) + 1
    for member_ids in _group_member_ids(project, section.id):
        ids = [eid for eid in member_ids if eid in elements_by_id]
        if not ids:
            continue
        count = len(ids)
        if count != section.subdivisions:
            report.stale_counts += 1
        for k, element_id in enumerate(ids):
            index = elements_by_id[element_id]
            element = elements[index]
            if not isinstance(element, ElasticBeamColumn):
                continue
            new_section = section_at(project, section, (k + 0.5) / count)
            key = _section_key(new_section)
            existing = section_by_key.get(key)
            if existing is None:
                existing = new_section.model_copy(
                    update={
                        "id": next_section,
                        "name": f"{section.name or 'Nonprismatic'} [{k + 1}/{count}]",
                    }
                )
                next_section += 1
                project.sections.append(existing)
                sections_by_id[existing.id] = existing
                section_by_key[key] = existing
            old_section = sections_by_id.get(element.section_id)
            rho = element.rho
            if isinstance(old_section, ElasticSection) and old_section.A > 0.0:
                rho = element.rho * (existing.A / old_section.A)
            elements[index] = element.model_copy(
                update={"section_id": existing.id, "rho": max(0.0, rho)}
            )
            report.elements += 1
        report.members += 1
    project.elements[:] = elements
    return report


def nonprismatic_template_ids(project: Project) -> set[int]:
    """The ids of every :class:`NonprismaticSection` in ``project``."""
    return {s.id for s in project.sections if isinstance(s, NonprismaticSection)}


__all__ = [
    "NONPRISMATIC_GROUP_PREFIX",
    "MaterializationReport",
    "RefreshReport",
    "materialize_nonprismatic",
    "nonprismatic_template_ids",
    "refresh_nonprismatic",
    "section_at",
]
