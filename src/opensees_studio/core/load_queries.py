"""Which loads act on one node or one element.

The property dock shows them under *Cargas aplicadas*, and the same query is
what a future schedule would read. Pure ``core``: no Qt, no OpenSees.

A load is reported per pattern it belongs to. The value is formatted with the
project's own units by the caller; here it is the raw number plus the kind, so
the panel and the tests read the same rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opensees_studio.core.loads import (
    FloorLoad,
    ImposedDisplacement,
    NodalLoad,
    PlainLoadPattern,
    PointElementLoad,
    SurfaceLoad,
    TemperatureLoad,
    TrapezoidalElementLoad,
    UniformElementLoad,
)


@dataclass(frozen=True)
class LoadRow:
    """One load acting on the selected entity, from one pattern."""

    pattern_id: int
    pattern: str
    kind: str
    """A key of ``nodal``, ``uniform``, ``trapezoidal``, ``point``, ``surface``, ``floor``, ``temperature``, ``imposed``."""
    detail: str
    """A short description: the components and where they act."""
    components: tuple[float, ...]
    """The raw values (forces, pressures), in project units."""


def _fmt(value: float) -> str:
    return f"{value:.4g}"


def _patterns(project: Any) -> list[PlainLoadPattern]:
    return [p for p in getattr(project, "load_patterns", []) if isinstance(p, PlainLoadPattern)]


def loads_on_node(project: Any, node_id: int) -> list[LoadRow]:
    """Every load that acts on ``node_id``, pattern by pattern."""
    rows: list[LoadRow] = []
    for pattern in _patterns(project):
        name = pattern.name or pattern.type
        for nodal in pattern.nodal_loads:
            if not isinstance(nodal, NodalLoad) or nodal.node_id != node_id:
                continue
            forces = nodal.forces
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="nodal",
                    detail=f"Fx {_fmt(forces[0])}, Fy {_fmt(forces[1])}, Fz {_fmt(forces[2])}",
                    components=tuple(float(v) for v in forces),
                )
            )
        for imposed in pattern.imposed_displacements:
            if not isinstance(imposed, ImposedDisplacement) or imposed.node_id != node_id:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="imposed",
                    detail=f"DOF {imposed.dof}: {_fmt(imposed.value)}",
                    components=(float(imposed.value),),
                )
            )
    return rows


def loads_on_element(project: Any, element_id: int) -> list[LoadRow]:
    """Every load that acts on ``element_id``, pattern by pattern."""
    rows: list[LoadRow] = []
    for pattern in _patterns(project):
        name = pattern.name or pattern.type
        for uniform in pattern.element_loads:
            if not isinstance(uniform, UniformElementLoad) or uniform.element_id != element_id:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="uniform",
                    detail=(f"wy {_fmt(uniform.wy)}, wz {_fmt(uniform.wz)}, wx {_fmt(uniform.wx)}"),
                    components=(uniform.wx, uniform.wy, uniform.wz),
                )
            )
        for point in pattern.point_loads:
            if not isinstance(point, PointElementLoad) or point.element_id != element_id:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="point",
                    detail=(
                        f"P {_fmt(point.px)}, {_fmt(point.py)}, {_fmt(point.pz)} at x/L {point.x:g}"
                    ),
                    components=(point.px, point.py, point.pz),
                )
            )
        for line in pattern.distributed_loads:
            if not isinstance(line, TrapezoidalElementLoad) or line.element_id != element_id:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="trapezoidal",
                    detail=(
                        f"x {line.x_start:g}-{line.x_end:g}: "
                        f"wy {_fmt(line.wy_start)}→{_fmt(line.wy_end)}, "
                        f"wz {_fmt(line.wz_start)}→{_fmt(line.wz_end)}"
                    ),
                    components=(
                        line.wx_start,
                        line.wy_start,
                        line.wz_start,
                        line.wx_end,
                        line.wy_end,
                        line.wz_end,
                    ),
                )
            )
        for surface in pattern.surface_loads:
            if not isinstance(surface, SurfaceLoad) or surface.element_id != element_id:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="surface",
                    detail=f"{_fmt(surface.value)} ({surface.direction})",
                    components=(surface.value,),
                )
            )
        for thermal in pattern.temperature_loads:
            if not isinstance(thermal, TemperatureLoad) or thermal.element_id != element_id:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="temperature",
                    detail=(
                        f"uniform {_fmt(thermal.uniform)}, "
                        f"gy {_fmt(thermal.gradient_y)}, gz {_fmt(thermal.gradient_z)}"
                    ),
                    components=(
                        thermal.uniform,
                        thermal.gradient_y,
                        thermal.gradient_z,
                    ),
                )
            )
        for floor in pattern.floor_loads:
            if not isinstance(floor, FloorLoad) or element_id not in floor.nodes:
                continue
            rows.append(
                LoadRow(
                    pattern_id=pattern.id,
                    pattern=name,
                    kind="floor",
                    detail=f"{_fmt(floor.value)} ({floor.distribution})",
                    components=(floor.value,),
                )
            )
    return rows
