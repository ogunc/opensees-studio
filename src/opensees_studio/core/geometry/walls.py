"""Reinforced concrete wall macro-elements: OpenSees ``MVLEM`` (2D).

The Multiple-Vertical-Line-Element Model (Vulcano, Bertero and Colotti 1988;
Orakcal, Wallace and Conte 2004) represents a wall segment between two joints
by ``m`` vertical uniaxial fibres across its length — each a concrete area and
the steel at a reinforcing ratio — and one horizontal shear spring at the
height ``c h`` above the bottom joint, about which the segment rotates
(``c = 0.4`` is the usual value). Flexure and axial load are coupled through
the fibres; shear is a separate force-deformation spring, so its material's
stiffness is ``G Aw / h`` for the segment's own height ``h``.

It is what gidopensees' ``FiberInt`` section and ``dispBeamColumnInt`` element
were for — a wall with flexure and shear — but OpenSeesPy 3.8 does not define
``section FiberInt``, so ``MVLEM`` is the wall model this application offers.

Only 2D models (three DOFs per joint). A wall is a stack of segments, the bottom
joint first: several segments per storey make the curvature, which a single
segment lumps at ``c h``, converge to the continuous one.

No Qt, no OpenSees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt, model_validator

from opensees_studio.core._base import Entity


class MVLEMElement(Entity):
    """``MVLEM``: a wall segment of vertical fibres and a shear spring (2D)."""

    type: Literal["MVLEM"] = "MVLEM"
    nodes: tuple[PositiveInt, PositiveInt]
    """Bottom joint, top joint."""
    density: float = Field(default=0.0, ge=0.0, description="Mass per unit volume (Dens).")
    c: float = Field(
        default=0.4, ge=0.0, le=1.0, description="Height of the centre of rotation over h."
    )
    thicknesses: tuple[PositiveFloat, ...] = Field(..., min_length=1)
    widths: tuple[PositiveFloat, ...] = Field(..., min_length=1)
    """Fibre widths along the wall length, from one end to the other."""
    steel_ratios: tuple[float, ...] = Field(..., min_length=1)
    concrete_material_ids: tuple[PositiveInt, ...] = Field(..., min_length=1)
    steel_material_ids: tuple[PositiveInt, ...] = Field(..., min_length=1)
    shear_material_id: PositiveInt

    @model_validator(mode="after")
    def _one_value_per_fibre(self) -> MVLEMElement:
        m = len(self.widths)
        lists = (
            self.thicknesses,
            self.steel_ratios,
            self.concrete_material_ids,
            self.steel_material_ids,
        )
        if any(len(values) != m for values in lists):
            raise ValueError(
                "MVLEM: give one thickness, steel ratio, concrete and steel material per fibre."
            )
        if any(not 0.0 <= r < 1.0 for r in self.steel_ratios):
            raise ValueError("MVLEM: steel ratios are between 0 and 1.")
        return self

    @property
    def fibres(self) -> int:
        return len(self.widths)

    @property
    def length(self) -> float:
        """Wall length: the sum of the fibre widths."""
        return float(sum(self.widths))

    @property
    def material_reference_ids(self) -> tuple[int, ...]:
        return (*self.concrete_material_ids, *self.steel_material_ids, self.shear_material_id)

    def opensees_args(self) -> list[object]:
        """Arguments after ``element('MVLEM', tag``."""
        return [
            self.density,
            *self.nodes,
            self.fibres,
            self.c,
            "-thick",
            *self.thicknesses,
            "-width",
            *self.widths,
            "-rho",
            *self.steel_ratios,
            "-matConcrete",
            *self.concrete_material_ids,
            "-matSteel",
            *self.steel_material_ids,
            "-matShear",
            self.shear_material_id,
        ]


def wall_fibres(
    length: float,
    fibres: int,
    *,
    boundary_length: float = 0.0,
    web_ratio: float,
    boundary_ratio: float | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Fibre widths and steel ratios of a wall of ``length``.

    With ``boundary_length`` > 0 each end of the wall is a boundary element of
    that length with its own (usually higher) ``boundary_ratio``, divided into
    fibres of about the web's width; the web takes the rest. Widths add up to
    ``length`` exactly.

    Raises:
        ValueError: too few fibres, or boundaries longer than the wall.
    """
    if fibres < 2:
        raise ValueError("A wall needs at least two fibres.")
    if length <= 0.0:
        raise ValueError("The wall length must be positive.")
    if boundary_length <= 0.0:
        width = length / fibres
        return (width,) * fibres, (web_ratio,) * fibres
    if 2.0 * boundary_length >= length:
        raise ValueError("The two boundary elements must be shorter than the wall.")
    ratio = web_ratio if boundary_ratio is None else boundary_ratio
    per_end = max(1, round(fibres * boundary_length / length))
    web = max(1, fibres - 2 * per_end)
    end_width = boundary_length / per_end
    web_width = (length - 2.0 * boundary_length) / web
    widths = (end_width,) * per_end + (web_width,) * web + (end_width,) * per_end
    ratios = (ratio,) * per_end + (web_ratio,) * web + (ratio,) * per_end
    return widths, ratios


# ──────────────────────────── members to walls ────────────────────────────
@dataclass(frozen=True)
class WallSpec:
    """A uniform wall section to give a stack of vertical members."""

    length: float
    thickness: float
    fibres: int
    concrete_material_id: int
    steel_material_id: int
    web_ratio: float
    boundary_length: float = 0.0
    boundary_ratio: float | None = None
    shear_modulus: float | None = None
    """``G`` of the shear springs created per segment height (``G L t / h``)."""
    shear_material_id: int | None = None
    """An existing shear material instead (used as is for every segment)."""
    c: float = 0.4
    density: float = 0.0


@dataclass
class WallConversion:
    """The materials and elements :func:`walls_from_members` makes."""

    materials: list[object]
    elements: list[MVLEMElement]
    skipped: list[int]
    """Selected elements that are not vertical two-joint members."""


def walls_from_members(
    project: object, element_ids: set[int], spec: WallSpec, *, first_material_id: int
) -> WallConversion:
    """Turn the selected vertical two-joint members into ``MVLEM`` segments.

    Each keeps its id and joints, ordered bottom to top. With ``shear_modulus``,
    one elastic shear material is created per distinct segment height, with the
    stiffness ``G L t / h`` of a wall panel of that height; with
    ``shear_material_id`` that material is used for every segment.

    Raises:
        ValueError: neither or both shear options, or a bad section.
    """
    from opensees_studio.core.materials import ElasticUniaxial

    if (spec.shear_modulus is None) == (spec.shear_material_id is None):
        raise ValueError("Give either a shear modulus or an existing shear material.")
    widths, ratios = wall_fibres(
        spec.length,
        spec.fibres,
        boundary_length=spec.boundary_length,
        web_ratio=spec.web_ratio,
        boundary_ratio=spec.boundary_ratio,
    )
    if spec.thickness <= 0.0:
        raise ValueError("The wall thickness must be positive.")
    coords = {n.id: n.coords for n in project.nodes}  # type: ignore[attr-defined]
    out = WallConversion(materials=[], elements=[], skipped=[])
    shear_by_height: dict[float, int] = {}
    next_id = first_material_id
    for element in project.elements:  # type: ignore[attr-defined]
        if element.id not in element_ids:
            continue
        nodes: tuple[int, ...] = tuple(getattr(element, "nodes", ()))
        if len(nodes) != 2 or isinstance(element, MVLEMElement):
            out.skipped.append(element.id)
            continue
        a, b = coords[nodes[0]], coords[nodes[1]]
        height = abs(b[2] - a[2])
        horizontal = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if height <= 0.0 or horizontal > 1e-6 * height:
            out.skipped.append(element.id)
            continue
        bottom, top = (nodes[0], nodes[1]) if a[2] < b[2] else (nodes[1], nodes[0])
        if spec.shear_material_id is not None:
            shear_id = spec.shear_material_id
        else:
            key = round(height, 12)
            if key not in shear_by_height:
                modulus = spec.shear_modulus or 0.0
                stiffness = modulus * spec.length * spec.thickness / height
                out.materials.append(
                    ElasticUniaxial(id=next_id, name=f"Wall shear h={height:g}", E=stiffness)
                )
                shear_by_height[key] = next_id
                next_id += 1
            shear_id = shear_by_height[key]
        m = len(widths)
        out.elements.append(
            MVLEMElement(
                id=element.id,
                nodes=(bottom, top),
                density=spec.density,
                c=spec.c,
                thicknesses=(spec.thickness,) * m,
                widths=widths,
                steel_ratios=ratios,
                concrete_material_ids=(spec.concrete_material_id,) * m,
                steel_material_ids=(spec.steel_material_id,) * m,
                shear_material_id=shear_id,
            )
        )
    return out
