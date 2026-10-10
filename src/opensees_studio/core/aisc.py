"""The AISC v16 shape library: pick a named shape, get a section.

The table (`data/aisc_v16.csv`, 1660 shapes) is US customary as published.
Nothing here converts silently: :func:`shape_to_elastic_section` takes the
project's unit system and scales the *geometry* — area by the square of the
length factor, second moments by the fourth power — because a shape comes from
a library in its own units. The dialog shows both the published and the
inserted values before anything is added to the model.

The data's provenance, licence and regeneration are in `data/README.md`.

Only a section's *geometry* comes from the library: `E` (and `G` for 3D) is a
material property and stays the caller's choice.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from opensees_studio.core.sections import (
    AngleShape,
    ElasticSection,
    FiberSection,
    Patch,
    PipeShape,
    RectShape,
    w_shape_patches,
)
from opensees_studio.core.units import UnitSystem, length_scale

#: Family code → human name, as the picker offers them.
FAMILY_LABELS: dict[str, str] = {
    "W": "W — wide flange",
    "HP": "HP — bearing pile",
    "M": "M — miscellaneous beam",
    "S": "S — American standard beam",
    "C": "C — American standard channel",
    "MC": "MC — miscellaneous channel",
    "WT": "WT — structural tee (W)",
    "MT": "MT — structural tee (M)",
    "ST": "ST — structural tee (S)",
    "L": "L — angle",
    "PIPE": "Pipe — round, seamless/welded",
    "HSS": "HSS — rectangular and square tube",
    "HSS_R": "HSS round — round tube",
}

#: Families built from two flanges and a web: they can also become a fibre section.
ISHAPE_FAMILIES = frozenset({"W", "HP", "M", "S", "C", "MC", "WT", "MT", "ST"})

#: The unit system the table is published in.
SOURCE_UNITS = UnitSystem.US_IN_KIP

#: ``core/aisc.py`` → the package's ``data`` directory.
_DATA = Path(__file__).resolve().parents[1] / "data" / "aisc_v16.csv"


class AISCShape(BaseModel):
    """One row of the AISC v16 table, in the units AISC publishes."""

    model_config = ConfigDict(frozen=True)

    family: str
    name: str
    weight: float | None = None
    """Nominal weight, lb/ft."""
    area: float
    """Cross-sectional area, in²."""
    d: float | None = None
    bf: float | None = None
    tw: float | None = None
    tf: float | None = None
    od: float | None = None
    tnom: float | None = None
    ix: float
    """Moment of inertia about the x-axis, in⁴ (the strong axis)."""
    zx: float | None = None
    sx: float | None = None
    rx: float | None = None
    iy: float | None = None
    zy: float | None = None
    sy: float | None = None
    ry: float | None = None
    j: float | None = None
    """Torsional constant, in⁴."""
    cw: float | None = None
    """Warping constant, in⁶."""

    @property
    def has_ishape_geometry(self) -> bool:
        """True when d, bf, tf and tw are all present (a flange-web section)."""
        return None not in (self.d, self.bf, self.tw, self.tf)


def _optional(value: str) -> float | None:
    return float(value) if value else None


@lru_cache(maxsize=1)
def load_shapes() -> dict[str, AISCShape]:
    """Every shape in the table, keyed by name (``"W14X90"``).

    Cached: the file is read once per process, on first use.
    """
    shapes: dict[str, AISCShape] = {}
    with _DATA.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            numeric = {
                key: _optional(row[key])
                for key in (
                    "weight",
                    "d",
                    "bf",
                    "tw",
                    "tf",
                    "od",
                    "tnom",
                    "zx",
                    "sx",
                    "rx",
                    "iy",
                    "zy",
                    "sy",
                    "ry",
                    "j",
                    "cw",
                )
            }
            shape = AISCShape(
                family=row["family"],
                name=row["name"],
                area=float(row["area"]),
                ix=float(row["ix"]),
                **numeric,
            )
            shapes[shape.name] = shape
    return shapes


def get_shape(name: str) -> AISCShape:
    """One shape by name, or a :exc:`KeyError` listing near misses."""
    shapes = load_shapes()
    try:
        return shapes[name]
    except KeyError:
        upper = name.strip().upper()
        close = sorted(n for n in shapes if upper in n.upper())[:5]
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        raise KeyError(f"{name!r} is not an AISC v16 shape.{hint}") from None


def families() -> list[str]:
    """The family codes present in the table, in the order the picker shows."""
    present = {shape.family for shape in load_shapes().values()}
    return [family for family in FAMILY_LABELS if family in present]


def shapes_of(family: str) -> list[AISCShape]:
    """Every shape of ``family``, in table order (roughly ascending weight)."""
    return [s for s in load_shapes().values() if s.family == family]


def shape_hint(shape: AISCShape) -> PipeShape | RectShape | AngleShape | None:
    """The truthful drawing hint for ``shape``, when the viewer has a kind for it.

    Only the kinds that exist today (pipe, rectangle, angle) are returned. A
    wide flange drawn as a solid rectangle would misrepresent it, so an
    I-shaped section gets no hint and the viewer falls back to its equivalent
    rectangle, which is documented as an approximation; the fibre route
    (:func:`shape_to_fiber_section`) draws the real profile in the meantime.
    """
    if shape.family in {"PIPE", "HSS_R"} and shape.od and shape.tnom:
        return PipeShape(od=shape.od, t=shape.tnom)
    if shape.family == "HSS" and shape.d and shape.bf and shape.tnom:
        return RectShape(d=shape.d, b=shape.bf)
    if shape.family == "L" and shape.d and shape.bf and shape.tf:
        return AngleShape(d=shape.d, b=shape.bf, t=shape.tf)
    return None


def shape_to_elastic_section(
    shape: AISCShape,
    *,
    elastic_modulus: float,
    shear_modulus: float | None = None,
    section_id: int = 1,
    name: str = "",
    units: UnitSystem = UnitSystem.SI_M_N,
    with_hint: bool = True,
) -> ElasticSection:
    """An :class:`ElasticSection` with this shape's geometry, in ``units``.

    The elastic and shear moduli are the caller's (they are material
    properties, not shape properties); the geometry is scaled from the table's
    US customary units by ``length_scale`` squared for the area and to the
    fourth power for the inertias.
    """
    factor = length_scale(SOURCE_UNITS, units)
    return ElasticSection(
        id=section_id,
        name=name or shape.name,
        E=elastic_modulus,
        G=shear_modulus,
        A=shape.area * factor**2,
        Iz=shape.ix * factor**4,
        Iy=(shape.iy * factor**4) if shape.iy is not None else None,
        J=(shape.j * factor**4) if shape.j is not None else None,
        shape=shape_hint(shape) if with_hint else None,
    )


def shape_to_fiber_section(
    shape: AISCShape,
    *,
    material_id: int,
    section_id: int = 1,
    name: str = "",
    n_web: int = 10,
    n_flange: int = 4,
) -> FiberSection:
    """A :class:`FiberSection` of the real profile, for an I-shaped family.

    The patches come from :func:`~opensees_studio.core.sections.w_shape_patches`,
    which reproduces OpenSees' ``WFSection2d`` fibre layout, so the section
    response matches the built-in shape. Units stay the project's: unlike the
    elastic route there is nothing to convert, because the caller supplies the
    dimensions.
    """
    if not shape.has_ishape_geometry:
        raise ValueError(
            f"{shape.name} has no flange-and-web geometry (d, bf, tf, tw); "
            "a fibre section needs those, so use the elastic route or a W-family shape."
        )
    assert shape.d is not None and shape.bf is not None  # narrowed by has_ishape_geometry
    assert shape.tw is not None and shape.tf is not None
    # ``w_shape_patches`` returns the concrete rectangle type; ``FiberSection``
    # takes the union, and lists are invariant, so each patch is checked
    # against the union here.
    patches: list[Patch] = [
        *w_shape_patches(
            material_id,
            d=shape.d,
            bf=shape.bf,
            tf=shape.tf,
            tw=shape.tw,
            n_web=n_web,
            n_flange=n_flange,
        )
    ]
    return FiberSection(id=section_id, name=name or shape.name, patches=patches)


def converted_geometry(shape: AISCShape, units: UnitSystem) -> dict[str, float]:
    """The values that would be inserted, for a dialog to show before it does."""
    factor = length_scale(SOURCE_UNITS, units)
    out = {"A": shape.area * factor**2, "Iz": shape.ix * factor**4}
    if shape.iy is not None:
        out["Iy"] = shape.iy * factor**4
    if shape.j is not None:
        out["J"] = shape.j * factor**4
    return out


__all__ = [
    "FAMILY_LABELS",
    "ISHAPE_FAMILIES",
    "SOURCE_UNITS",
    "AISCShape",
    "converted_geometry",
    "families",
    "get_shape",
    "load_shapes",
    "shape_hint",
    "shape_to_elastic_section",
    "shape_to_fiber_section",
    "shapes_of",
]
