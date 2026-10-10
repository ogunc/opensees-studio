"""Unit system metadata, display labels and display conversion.

OpenSees is unit-agnostic: it never converts. The engineer picks a
consistent system (SI, kip-in, etc.) for the model and sticks to it.
We never rewrite the numbers an engineer typed, either — but a project
may be *shown* in a second system (SAP2000's "Set Display Units"): the
model stays in ``ProjectMeta.units``, and every number the analysis
produced — force diagrams, displacements, tables, curves — is converted
to ``ProjectMeta.display_units`` for display only.

The :func:`labels_for` helper returns an :class:`UnitLabels` bundle
matching SAP2000's "Set Program Default Display Units" semantics:
length / force / moment / stress / curvature / rotation labels, all
driven by :class:`UnitSystem` enum. :class:`UnitConverter` carries the
factors a result view needs so no view has to know that a kip is
4448.22 N.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class UnitSystem(str, Enum):  # noqa: UP042 - serialized into .osmodel files; str() output must not change
    """Consistent unit systems supported by the application."""

    SI_M_N = "SI (m, N, kg, s, Pa)"
    """Length: m, Force: N, Mass: kg, Time: s, Stress: Pa."""

    SI_MM_N = "SI (mm, N, t, s, MPa)"
    """Length: mm, Force: N, Mass: t, Time: s, Stress: MPa."""

    US_FT_KIP = "US (ft, kip, slug, s, ksf)"
    """Length: ft, Force: kip, Mass: slug, Time: s, Stress: ksf."""

    US_IN_KIP = "US (in, kip, kip·s²/in, s, ksi)"
    """Length: in, Force: kip, Mass: kip·s²/in, Time: s, Stress: ksi."""


@dataclass(frozen=True)
class UnitLabels:
    """Display strings for each basic quantity in a unit system.

    Consumed by result views (pushover curve, diagrams, tables) to
    label axes without hard-coding any particular set of units.
    """

    length: str  # "m", "mm", "in", "ft"
    force: str  # "N", "kip"
    moment: str  # "N·m", "kip·in"
    stress: str  # "Pa", "MPa", "ksi", "ksf"
    curvature: str  # "1/m", "1/in", …
    rotation: str  # "rad" (always, no unit variants in practice)


_LABELS: dict[UnitSystem, UnitLabels] = {
    UnitSystem.SI_M_N: UnitLabels(
        length="m",
        force="N",
        moment="N·m",
        stress="Pa",
        curvature="1/m",
        rotation="rad",
    ),
    UnitSystem.SI_MM_N: UnitLabels(
        length="mm",
        force="N",
        moment="N·mm",
        stress="MPa",
        curvature="1/mm",
        rotation="rad",
    ),
    UnitSystem.US_FT_KIP: UnitLabels(
        length="ft",
        force="kip",
        moment="kip·ft",
        stress="ksf",
        curvature="1/ft",
        rotation="rad",
    ),
    UnitSystem.US_IN_KIP: UnitLabels(
        length="in",
        force="kip",
        moment="kip·in",
        stress="ksi",
        curvature="1/in",
        rotation="rad",
    ),
}


def labels_for(units: UnitSystem) -> UnitLabels:
    """Return the label bundle for the given unit system."""
    return _LABELS[units]


#: Standard gravity expressed in each system's length/s^2 (9.80665 m/s^2).
_GRAVITY: dict[UnitSystem, float] = {
    UnitSystem.SI_M_N: 9.80665,
    UnitSystem.SI_MM_N: 9806.65,
    UnitSystem.US_FT_KIP: 32.17405,
    UnitSystem.US_IN_KIP: 386.0886,
}


def gravity(units: UnitSystem) -> float:
    """Standard gravity in the acceleration unit of ``units`` (length/s^2)."""
    return _GRAVITY[units]


#: Length of one unit of each system, in metres.
_LENGTH_M: dict[UnitSystem, float] = {
    UnitSystem.SI_M_N: 1.0,
    UnitSystem.SI_MM_N: 1e-3,
    UnitSystem.US_FT_KIP: 0.3048,
    UnitSystem.US_IN_KIP: 0.0254,
}


def metres_per_unit(units: UnitSystem) -> float:
    """How many metres one length unit of ``units`` is worth."""
    return _LENGTH_M[units]


def length_scale(source: UnitSystem, target: UnitSystem) -> float:
    """Factor taking a length from ``source`` units to ``target`` units.

    The application does not convert values an engineer typed (OpenSees is
    unit-agnostic and the chosen system is recorded, not applied). This exists
    for the one case where a value arrives in a unit system of its own — a
    shape from a published library, which is in US customary units — so the
    conversion is explicit, shown to the user, and never applied behind their
    back. Areas scale by the square and second moments by the fourth power.
    """
    return _LENGTH_M[source] / _LENGTH_M[target]


#: Newtons in one force unit of each system (SI: N, US: kip = 1000 lbf).
_FORCE_N: dict[UnitSystem, float] = {
    UnitSystem.SI_M_N: 1.0,
    UnitSystem.SI_MM_N: 1.0,
    UnitSystem.US_FT_KIP: 4448.2216152605,
    UnitSystem.US_IN_KIP: 4448.2216152605,
}


def newtons_per_unit(units: UnitSystem) -> float:
    """How many newtons one force unit of ``units`` is worth."""
    return _FORCE_N[units]


def force_scale(source: UnitSystem, target: UnitSystem) -> float:
    """Factor taking a force from ``source`` units to ``target`` units."""
    return _FORCE_N[source] / _FORCE_N[target]


def moment_scale(source: UnitSystem, target: UnitSystem) -> float:
    """Factor taking a moment (force × length) from ``source`` to ``target``."""
    return force_scale(source, target) * length_scale(source, target)


def stress_scale(source: UnitSystem, target: UnitSystem) -> float:
    """Factor taking a stress (force / length²) from ``source`` to ``target``."""
    return force_scale(source, target) / length_scale(source, target) ** 2


def mass_scale(source: UnitSystem, target: UnitSystem) -> float:
    """Factor taking a *mass* from ``source`` units to ``target`` units.

    The coherent mass unit of a force/length system is ``force·s²/length``: the
    unit that makes ``F = m·a`` come out in the system's own force unit. For the
    US systems that is ``kip·s²/ft`` (1000 slug) and ``kip·s²/in``. Densities —
    what a material library carries — scale with mass over length cubed.
    """
    return force_scale(source, target) / length_scale(source, target)


def density_scale(source: UnitSystem, target: UnitSystem) -> float:
    """Factor taking a mass density (mass / length³) from ``source`` to ``target``.

    ``1 kg/m³`` is ``1e-12 t/mm³`` and ``9.3575e-11 kip·s²/in⁴``; the ASCE 7
    tabulated 150 lb/ft³ of reinforced concrete becomes 2402.77 kg/m³.
    """
    return mass_scale(source, target) / length_scale(source, target) ** 3


#: The coherent mass-density unit of each system — mass over length cubed, with
#: mass = force·s²/length so that a density times a volume gives a mass whose
#: weight comes out in the system's own force unit.
_MASS_DENSITY_LABEL: dict[UnitSystem, str] = {
    UnitSystem.SI_M_N: "kg/m³",
    UnitSystem.SI_MM_N: "t/mm³",
    UnitSystem.US_FT_KIP: "kip·s²/ft⁴",
    UnitSystem.US_IN_KIP: "kip·s²/in⁴",
}


def mass_density_label(units: UnitSystem) -> str:
    """The unit a mass density is expressed in for ``units``."""
    return _MASS_DENSITY_LABEL[units]


#: Quantity kinds a result view can declare, mapped to their factor name.
#: Velocities and accelerations are lengths per time power: only the length
#: changes between systems, since both systems share the second.
KIND_LENGTH = "length"
KIND_FORCE = "force"
KIND_MOMENT = "moment"
KIND_STRESS = "stress"
KIND_ROTATION = "rotation"

_KIND_KEY: dict[str, str] = {
    KIND_LENGTH: "length",
    "velocity": KIND_LENGTH,
    "accel": KIND_LENGTH,
    "acceleration": KIND_LENGTH,
    "curvature": KIND_LENGTH,  # 1/length → same factor as length, inverted
    KIND_FORCE: "force",
    "shear": KIND_FORCE,
    "axial": KIND_FORCE,
    KIND_MOMENT: "moment",
    "torque": KIND_MOMENT,
    KIND_STRESS: "stress",
    KIND_ROTATION: "identity",
}


@dataclass(frozen=True)
class UnitConverter:
    """The factors that take a result value from the model's system to the display one.

    ``display`` is ``None`` when the project is shown in its own system (the
    default), in which case every factor is 1.0 and :attr:`is_identity` is true.
    Curvature is the inverse of a length, so its factor is ``1 / length``.
    """

    model: UnitSystem = UnitSystem.SI_M_N
    display: UnitSystem | None = None

    @classmethod
    def of(cls, meta: Any | None) -> UnitConverter:
        """Build the converter of a ``ProjectMeta`` (or any object with ``units``).

        A missing ``display_units`` — every file written before the field
        existed — means "show the model in its own system".
        """
        if meta is None:
            return cls()
        return cls(
            model=meta.units,
            display=getattr(meta, "display_units", None),
        )

    @property
    def target(self) -> UnitSystem:
        """The system results are shown in (the model's own when none is set)."""
        return self.model if self.display is None else self.display

    @property
    def is_identity(self) -> bool:
        return self.target is self.model

    @property
    def labels(self) -> UnitLabels:
        """Labels of the *display* system."""
        return labels_for(self.target)

    @property
    def length(self) -> float:
        return length_scale(self.model, self.target)

    @property
    def force(self) -> float:
        return force_scale(self.model, self.target)

    @property
    def moment(self) -> float:
        return moment_scale(self.model, self.target)

    @property
    def stress(self) -> float:
        return stress_scale(self.model, self.target)

    def factor(self, kind: str) -> float:
        """Conversion factor for a quantity ``kind`` (see the ``KIND_*`` constants)."""
        key = _KIND_KEY.get(kind)
        if key is None:
            raise KeyError(f"Unknown quantity kind: {kind!r}")
        if key == "identity":
            return 1.0
        value = float(getattr(self, key))
        # Curvature is the inverse of a length, so its factor inverts too.
        return 1.0 / value if kind == "curvature" else value

    def apply(self, kind: str, value: Any) -> Any:
        """Convert one value (float or NumPy array) of quantity ``kind``."""
        factor = self.factor(kind)
        if factor == 1.0:
            return value
        return value * factor
