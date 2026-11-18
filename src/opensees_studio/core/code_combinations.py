"""Design-code combination generators.

Each generator turns a mapping *load role → analysis cases* (see
:data:`opensees_studio.core.combinations.LOAD_ROLES`) into ordinary
:class:`~opensees_studio.core.combinations.CombinationTerm` lists: a generated
set is just a set of editable linear-add combinations. The codes:

- **ASCE 7-16 LRFD** (Section 2.3.1) and **ASD** (Section 2.4.1),
- **EN 1990** fundamental combinations for ultimate limit states (equation
  6.10 with the ψ0 factors of Table A1.1), the accidental/seismic combination
  (6.11b) and the serviceability characteristic, frequent and quasi-permanent
  combinations (6.14b to 6.16b),
- **TS 500 / TBDY 2018**: 1.4G+1.6Q, G+nQ±E, 0.9G±E and the TS 500 wind
  combinations.

How a role acts: a *dead* (permanent) role enters every combination with all
its cases. Wind and earthquake cases act in both signs (a response spectrum
case, already ``±peak``, in one), and with ``orthogonal`` the earthquake cases
combine by the 100%/30% rule (``±Ex ± 0.3Ey``, ``±0.3Ex ± Ey``). Roof live,
snow and rain cases are alternatives (one combination per case); live cases
enter together.

The factors are the standards' own and the generators leave judgement to the
engineer (the occupancy-dependent live-load reduction, favourable versus
unfavourable permanent action, the national annex): edit what is generated.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from opensees_studio.core.combinations import (
    LOAD_ROLES,
    CombinationTerm,
    asce7_16_lrfd,
    lateral_variants,
    scaled_parts,
    variant_name,
)

# ─────────────────────────── descriptions ───────────────────────────
GeneratorOptions = Mapping[str, Any]


@dataclass(frozen=True)
class GeneratorOption:
    """One setting of a generator, enough for a dialog to build a widget."""

    key: str
    label: str
    kind: str
    """``bool``, ``float`` or ``choice``."""
    default: Any
    choices: tuple[tuple[str, str], ...] = ()
    """``(value, label)`` pairs of a ``choice`` option."""
    tip: str = ""


@dataclass(frozen=True)
class GeneratedCombination:
    """A generated combination: name, terms, and the envelope group it belongs to."""

    name: str
    terms: list[CombinationTerm]
    group: str


@dataclass(frozen=True)
class CodeSpec:
    """A design code the dialog can generate combinations for."""

    key: str
    label: str
    summary: str
    roles: tuple[str, ...]
    """Load roles the code uses; a case tagged with another one is left out."""
    options: tuple[GeneratorOption, ...]
    generate: Callable[..., list[GeneratedCombination]]


ORTHOGONAL = GeneratorOption(
    "orthogonal",
    "Earthquake: 100% + 30% orthogonal rule",
    "bool",
    False,
    tip="With several earthquake cases, each acts at 100% with the others at 30%, in all signs.",
)

# ─────────────────────────── the term builder ───────────────────────────
Part = tuple[float, list[int]]


@dataclass
class _Choice:
    token: str
    parts: list[Part]


@dataclass
class _Slot:
    """What one load contributes to a combination: a choice per generated combination."""

    choices: list[_Choice]
    required: bool = False
    optional: bool = False
    """The combination may also be made without this load."""


def _num(value: float) -> str:
    value = round(value, 10)
    return "" if value == 1.0 else f"{value:g}"


class _Builder:
    """Slots and joins for the generators of this module."""

    def __init__(
        self,
        roles: Mapping[str, Iterable[int]],
        *,
        peak_cases: Iterable[int],
        case_names: Mapping[int, str],
        symbols: Mapping[str, str],
        orthogonal: bool = False,
    ) -> None:
        self.by_role = {role: list(dict.fromkeys(roles.get(role, ()))) for role in LOAD_ROLES}
        self.peaks = list(peak_cases)
        self.names = dict(case_names)
        self.symbols = dict(symbols)
        self.orthogonal = orthogonal

    def symbol(self, role: str) -> str:
        return self.symbols.get(role, role)

    def token(self, role: str, cid: int) -> str:
        """``W``, or ``W:wind X`` when several cases carry the role."""
        if len(self.by_role[role]) > 1:
            return f"{self.symbol(role)}:{self.names.get(cid, cid)}"
        return self.symbol(role)

    def all_of(self, role: str, factor: float, *, required: bool = False) -> _Slot:
        """Every case of ``role`` together at ``factor``."""
        cases = self.by_role[role]
        if not cases or factor == 0.0:
            return _Slot([], required)
        return _Slot([_Choice(f"{_num(factor)}{self.symbol(role)}", [(factor, cases)])], required)

    def one_of(self, roles: Sequence[str], factor: float, *, required: bool = False) -> _Slot:
        """One case of ``roles`` at a time at ``factor``."""
        if factor == 0.0:
            return _Slot([], required)
        return _Slot(
            [
                _Choice(f"{_num(factor)}{self.token(role, cid)}", [(factor, [cid])])
                for role in roles
                for cid in self.by_role[role]
            ],
            required,
        )

    def lateral(self, role: str, factor: float, *, required: bool = False) -> _Slot:
        """Every way the cases of ``role`` act (signs, orthogonal rule) at ``factor``."""
        if factor == 0.0:
            return _Slot([], required)

        def token(cid: int, role: str = role) -> str:
            return self.token(role, cid)

        variants = lateral_variants(
            self.by_role[role],
            self.peaks,
            orthogonal=self.orthogonal and role == "E",
        )
        return _Slot(
            [
                _Choice(
                    variant_name(factor, v, token),
                    scaled_parts(factor, v),
                )
                for v in variants
            ],
            required,
        )

    def combine(self, slots: Sequence[_Slot], prefix: str = "") -> list[tuple[str, list[Part]]]:
        """One ``(name, parts)`` per way of picking a choice from every non-empty slot.

        Nothing is produced when a required slot is empty.
        """
        if any(s.required and not s.choices for s in slots):
            return []
        absent = _Choice("", [])
        active = [[*s.choices, absent] if s.optional else s.choices for s in slots if s.choices]
        out = []
        for picks in itertools.product(*active):
            name = ""
            for pick in picks:
                if not pick.token:
                    continue
                joined = pick.token if pick.token[0] in "+-" else f"+{pick.token}"
                name += joined
            name = name[1:] if name.startswith("+") else name
            out.append((prefix + name, [p for pick in picks for p in pick.parts]))
        return out


def _terms(parts: Iterable[Part]) -> list[CombinationTerm]:
    merged: dict[int, float] = {}
    for factor, ids in parts:
        for cid in ids:
            merged[cid] = merged.get(cid, 0.0) + factor
    return [CombinationTerm(ref_id=cid, factor=round(f, 10)) for cid, f in merged.items()]


def _collect(
    group: str,
    sets: Iterable[Sequence[_Slot]],
    builder: _Builder,
    seen: set[tuple[tuple[int, float], ...]],
    prefix: str = "",
) -> list[GeneratedCombination]:
    """Expand ``sets`` of slots, leaving out a combination equal to one already made."""
    out: list[GeneratedCombination] = []
    for slots in sets:
        for name, parts in builder.combine(slots, prefix):
            terms = _terms(parts)
            key = tuple(sorted((t.ref_id, t.factor) for t in terms))
            if not terms or key in seen:
                continue
            seen.add(key)
            out.append(GeneratedCombination(name, terms, group))
    return out


# ─────────────────────────── ASCE 7-16 ───────────────────────────
def generate_asce7_lrfd(
    roles: Mapping[str, Iterable[int]],
    *,
    peak_cases: Iterable[int] = (),
    case_names: Mapping[int, str] | None = None,
    options: GeneratorOptions | None = None,
) -> list[GeneratedCombination]:
    """ASCE 7-16 2.3.1, see :func:`opensees_studio.core.combinations.asce7_16_lrfd`."""
    opts = options or {}
    return [
        GeneratedCombination(name, terms, "LRFD")
        for name, terms in asce7_16_lrfd(
            roles, peak_cases=peak_cases, orthogonal=bool(opts.get("orthogonal", False))
        )
    ]


def generate_asce7_asd(
    roles: Mapping[str, Iterable[int]],
    *,
    peak_cases: Iterable[int] = (),
    case_names: Mapping[int, str] | None = None,
    options: GeneratorOptions | None = None,
) -> list[GeneratedCombination]:
    """ASCE 7-16 Section 2.4.1 basic allowable stress design combinations.

    1. D
    2. D + L
    3. D + (Lr or S or R)
    4. D + 0.75L + 0.75(Lr or S or R)
    5. D + (0.6W or 0.7E)
    6. D + 0.75L + 0.75(0.6W) + 0.75(Lr or S or R), and
       D + 0.75L + 0.75(0.7E) + 0.75S
    7. 0.6D + 0.6W
    8. 0.6D + 0.7E

    A combination is made only when every load it names is present (``D``
    always is); the standard's 0.6D is the overturning and uplift check.
    """
    b = _Builder(
        roles,
        peak_cases=peak_cases,
        case_names=case_names or {},
        symbols={},
        orthogonal=bool((options or {}).get("orthogonal", False)),
    )
    if not b.by_role["D"]:
        return []
    roof = ("Lr", "S", "R")

    def dead(f: float = 1.0) -> _Slot:
        return b.all_of("D", f, required=True)

    sets = [
        [dead()],
        [dead(), b.all_of("L", 1.0, required=True)],
        [dead(), b.one_of(roof, 1.0, required=True)],
        [dead(), b.all_of("L", 0.75, required=True), b.one_of(roof, 0.75, required=True)],
        [dead(), b.lateral("W", 0.6, required=True)],
        [dead(), b.lateral("E", 0.7, required=True)],
        [dead(), b.all_of("L", 0.75), b.lateral("W", 0.45, required=True), b.one_of(roof, 0.75)],
        [
            dead(),
            b.all_of("L", 0.75),
            b.lateral("E", 0.525, required=True),
            b.one_of(("S",), 0.75),
        ],
        [dead(0.6), b.lateral("W", 0.6, required=True)],
        [dead(0.6), b.lateral("E", 0.7, required=True)],
    ]
    return _collect("ASD", sets, b, set())


# ─────────────────────────── EN 1990 ───────────────────────────
EN_IMPOSED_PSI: dict[str, tuple[float, float, float]] = {
    "A": (0.7, 0.5, 0.3),
    "B": (0.7, 0.5, 0.3),
    "C": (0.7, 0.7, 0.6),
    "D": (0.7, 0.7, 0.6),
    "E": (1.0, 0.9, 0.8),
    "F": (0.7, 0.7, 0.6),
    "G": (0.7, 0.5, 0.3),
    "H": (0.0, 0.0, 0.0),
}
"""EN 1990 Table A1.1 ``(ψ0, ψ1, ψ2)`` of imposed loads on buildings, by category."""

EN_IMPOSED_LABELS: dict[str, str] = {
    "A": "A  Domestic, residential",
    "B": "B  Offices",
    "C": "C  Congregation areas",
    "D": "D  Shopping areas",
    "E": "E  Storage areas",
    "F": "F  Traffic, vehicles up to 30 kN",
    "G": "G  Traffic, vehicles 30 to 160 kN",
    "H": "H  Roofs",
}
EN_SNOW_PSI = (0.5, 0.2, 0.0)
EN_SNOW_HIGH_PSI = (0.7, 0.5, 0.2)
EN_WIND_PSI = (0.6, 0.2, 0.0)
EN_ROOF_PSI = EN_IMPOSED_PSI["H"]
EN_GAMMA_G = 1.35
EN_GAMMA_G_FAVOURABLE = 1.0
EN_GAMMA_Q = 1.5
EN_SYMBOLS = {"D": "G", "L": "Q", "Lr": "Qr", "S": "S", "R": "R", "W": "W", "E": "E"}


def en1990_psi(
    role: str, *, imposed_category: str = "A", snow_above_1000m: bool = False
) -> tuple[float, float, float]:
    """``(ψ0, ψ1, ψ2)`` of a variable role (``L``, ``Lr``, ``S`` or ``W``)."""
    if role == "L":
        return EN_IMPOSED_PSI[imposed_category]
    if role == "Lr":
        return EN_ROOF_PSI
    if role == "S":
        return EN_SNOW_HIGH_PSI if snow_above_1000m else EN_SNOW_PSI
    if role == "W":
        return EN_WIND_PSI
    raise ValueError(f"EN 1990 has no ψ factors for role {role!r}.")


def generate_en1990(
    roles: Mapping[str, Iterable[int]],
    *,
    peak_cases: Iterable[int] = (),
    case_names: Mapping[int, str] | None = None,
    options: GeneratorOptions | None = None,
) -> list[GeneratedCombination]:
    """EN 1990 combinations of actions for buildings.

    Variable actions are the roles ``L`` (imposed, category from the
    ``imposed_category`` option), ``Lr`` (roof), ``S`` and ``W``; ``D`` is the
    permanent action and ``E`` the seismic one (rain has no EN 1990 factors
    and is left out).

    - **ULS, equation 6.10**: ``γG G + γQ Q1 + Σ γQ ψ0,i Qi`` with γG = 1.35,
      γQ = 1.5, each variable action in turn as the leading one Q1, and ``γG G``
      alone. With ``favourable_permanent`` the set is repeated with γG = 1.0
      (a permanent action that relieves the effect, e.g. uplift).
    - **ULS accidental/seismic, 6.11b**: ``G + E + Σ ψ2,i Qi``.
    - **SLS characteristic**: ``G + Q1 + Σ ψ0,i Qi``.
    - **SLS frequent**: ``G + ψ1,1 Q1 + Σ ψ2,i Qi``.
    - **SLS quasi-permanent**: ``G + Σ ψ2,i Qi``.

    Wind acts in both signs; the other variable actions are one combination
    per case (live cases together).
    """
    opts = options or {}
    b = _Builder(
        roles,
        peak_cases=peak_cases,
        case_names=case_names or {},
        symbols=EN_SYMBOLS,
        orthogonal=bool(opts.get("orthogonal", False)),
    )
    if not b.by_role["D"]:
        return []
    category = str(opts.get("imposed_category", "A"))
    high = bool(opts.get("snow_above_1000m", False))
    psi = {
        role: en1990_psi(role, imposed_category=category, snow_above_1000m=high)
        for role in ("L", "Lr", "S", "W")
    }
    variable = [r for r in ("L", "Lr", "S", "W") if b.by_role[r]]

    def load(role: str, factor: float, *, optional: bool = False) -> _Slot:
        if role == "L":
            slot = b.all_of("L", factor)
        elif role == "W":
            slot = b.lateral("W", factor)
        else:
            slot = b.one_of((role,), factor)
        slot.optional = optional
        return slot

    def with_leading(g: float, q: float, leading: str) -> list[_Slot]:
        """Permanent at ``g``, the leading action at ``q``, the others at ``q ψ0``."""
        slots = [b.all_of("D", g, required=True)]
        for role in variable:
            slots.append(
                load(
                    role,
                    q if role == leading else q * psi[role][0],
                    optional=role != leading,
                )
            )
        return slots

    out: list[GeneratedCombination] = []

    def permanent_only(g: float) -> list[Sequence[_Slot]]:
        return [[b.all_of("D", g, required=True)]]

    # ULS, 6.10: leading action at γQ, accompanying at γQ ψ0
    uls_seen: set[tuple[tuple[int, float], ...]] = set()
    gammas = [EN_GAMMA_G]
    if opts.get("favourable_permanent", False):
        gammas.append(EN_GAMMA_G_FAVOURABLE)
    for g in gammas:
        sets = permanent_only(g) + [with_leading(g, EN_GAMMA_Q, r) for r in variable]
        out += _collect("ULS", sets, b, uls_seen, prefix="ULS ")

    # ULS accidental/seismic, 6.11b: G + E + Σψ2 Q
    seismic = [
        [
            b.all_of("D", 1.0, required=True),
            b.lateral("E", 1.0, required=True),
            *[load(r, psi[r][2]) for r in variable],
        ]
    ]
    out += _collect("ULS seismic", seismic, b, set(), prefix="ULS ")

    # SLS characteristic: leading at 1.0, accompanying at ψ0
    out += _collect(
        "SLS characteristic",
        [with_leading(1.0, 1.0, r) for r in variable] or permanent_only(1.0),
        b,
        set(),
        prefix="SLS char ",
    )
    # SLS frequent: leading at ψ1, accompanying at ψ2
    freq_sets = []
    for lead in variable:
        slots = [b.all_of("D", 1.0, required=True)]
        for role in variable:
            slots.append(
                load(
                    role,
                    psi[role][1] if role == lead else psi[role][2],
                    optional=role != lead,
                )
            )
        freq_sets.append(slots)
    out += _collect("SLS frequent", freq_sets or permanent_only(1.0), b, set(), prefix="SLS freq ")
    # SLS quasi-permanent: G + Σψ2 Q
    quasi = [[b.all_of("D", 1.0, required=True), *[load(r, psi[r][2]) for r in variable]]]
    out += _collect("SLS quasi-permanent", quasi, b, set(), prefix="SLS quasi ")
    return out


# ─────────────────────────── TS 500 / TBDY 2018 ───────────────────────────
TBDY_SYMBOLS = {"D": "G", "L": "Q"}
TS500_GAMMA_G = 1.4
TS500_GAMMA_Q = 1.6
TS500_WIND_Q = 1.3
TS500_WIND = 1.3


def generate_tbdy(
    roles: Mapping[str, Iterable[int]],
    *,
    peak_cases: Iterable[int] = (),
    case_names: Mapping[int, str] | None = None,
    options: GeneratorOptions | None = None,
) -> list[GeneratedCombination]:
    """TS 500 / TBDY 2018 combinations for reinforced concrete design.

    1. 1.4G + 1.6Q (TS 500 gravity)
    2. G + nQ ± E (TBDY 2018 seismic)
    3. 0.9G ± E
    4. G + 1.3Q ± 1.3W (TS 500 wind)
    5. 0.9G ± 1.3W

    ``G`` is the Dead role, ``Q`` Live, ``E`` Earthquake (a response spectrum
    case gives one combination; a static one both signs; ``orthogonal`` adds
    the 100% + 30% rule of two horizontal components) and ``W`` Wind. ``n`` is
    the live load participation (the ``live_participation`` option, 1.0 by
    default; TBDY 2018 Table 4.3 gives 0.3 for housing and offices). Roof
    live, snow and rain cases are not used.
    """
    opts = options or {}
    b = _Builder(
        roles,
        peak_cases=peak_cases,
        case_names=case_names or {},
        symbols=TBDY_SYMBOLS,
        orthogonal=bool(opts.get("orthogonal", False)),
    )
    if not b.by_role["D"]:
        return []
    n = float(opts.get("live_participation", 1.0))
    if n < 0.0:
        raise ValueError("The live load participation n must not be negative.")

    def dead(f: float) -> _Slot:
        return b.all_of("D", f, required=True)

    sets = [
        [dead(TS500_GAMMA_G), b.all_of("L", TS500_GAMMA_Q, required=True)],
        [dead(1.0), b.all_of("L", n), b.lateral("E", 1.0, required=True)],
        [dead(0.9), b.lateral("E", 1.0, required=True)],
        [dead(1.0), b.all_of("L", TS500_WIND_Q), b.lateral("W", TS500_WIND, required=True)],
        [dead(0.9), b.lateral("W", TS500_WIND, required=True)],
    ]
    return _collect("TBDY", sets, b, set())


# ─────────────────────────── registry ───────────────────────────
CODES: dict[str, CodeSpec] = {
    "asce7_lrfd": CodeSpec(
        "asce7_lrfd",
        "ASCE 7-16 LRFD",
        "Section 2.3.1: 1.4D; 1.2D + 1.6L + 0.5(Lr or S or R); 1.2D + 1.6(Lr or S or R) + "
        "(L or 0.5W); 1.2D + 1.0W + L + 0.5(Lr or S or R); 1.2D + 1.0E + L + 0.2S; "
        "0.9D + 1.0W; 0.9D + 1.0E. The live load factor in the last three is 1.0 (the 0.5 "
        "exception depends on occupancy).",
        ("D", "L", "Lr", "S", "R", "W", "E"),
        (ORTHOGONAL,),
        generate_asce7_lrfd,
    ),
    "asce7_asd": CodeSpec(
        "asce7_asd",
        "ASCE 7-16 ASD",
        "Section 2.4.1: D; D + L; D + (Lr or S or R); D + 0.75L + 0.75(Lr or S or R); "
        "D + (0.6W or 0.7E); D + 0.75L + 0.75(0.6W) + 0.75(Lr or S or R); "
        "D + 0.75L + 0.75(0.7E) + 0.75S; 0.6D + 0.6W; 0.6D + 0.7E.",
        ("D", "L", "Lr", "S", "R", "W", "E"),
        (ORTHOGONAL,),
        generate_asce7_asd,
    ),
    "en1990": CodeSpec(
        "en1990",
        "EN 1990",
        "Equation 6.10 (γG = 1.35, γQ = 1.5, ψ0 of Table A1.1, each variable action leading in "
        "turn), the seismic combination G + E + Σψ2 Q, and the serviceability characteristic, "
        "frequent and quasi-permanent combinations. Rain has no EN 1990 factors.",
        ("D", "L", "Lr", "S", "W", "E"),
        (
            GeneratorOption(
                "imposed_category",
                "Imposed load category",
                "choice",
                "A",
                tuple(EN_IMPOSED_LABELS.items()),
                "Selects ψ0, ψ1, ψ2 of the Live cases (Table A1.1).",
            ),
            GeneratorOption(
                "snow_above_1000m",
                "Snow site above 1000 m",
                "bool",
                False,
                tip="ψ0, ψ1, ψ2 of snow: 0.7, 0.5, 0.2 instead of 0.5, 0.2, 0.",
            ),
            GeneratorOption(
                "favourable_permanent",
                "Also with favourable permanent action (γG = 1.0)",
                "bool",
                False,
                tip="Repeats the ultimate combinations with γG = 1.0, for uplift and overturning.",
            ),
            ORTHOGONAL,
        ),
        generate_en1990,
    ),
    "tbdy": CodeSpec(
        "tbdy",
        "TS 500 / TBDY 2018",
        "1.4G + 1.6Q; G + nQ ± E; 0.9G ± E (TBDY 2018); G + 1.3Q ± 1.3W and 0.9G ± 1.3W "
        "(TS 500). Roof live, snow and rain cases are not used.",
        ("D", "L", "W", "E"),
        (
            GeneratorOption(
                "live_participation",
                "Live load participation n in G + nQ ± E",
                "float",
                1.0,
                tip="TBDY 2018 Table 4.3: 0.3 for housing and offices, 0.6 for storage, 1.0 here.",
            ),
            ORTHOGONAL,
        ),
        generate_tbdy,
    ),
}
DEFAULT_CODE = "asce7_lrfd"


def default_options(code: str) -> dict[str, Any]:
    """The default value of every option of ``code``."""
    return {o.key: o.default for o in CODES[code].options}


def unused_roles(code: str, roles: Mapping[str, Iterable[int]]) -> list[str]:
    """Roles carrying cases that ``code`` does not use."""
    return [r for r in LOAD_ROLES if list(roles.get(r, ())) and r not in CODES[code].roles]


PLACEHOLDER_CASE_NAMES: dict[str, tuple[str, ...]] = {
    "D": ("DEAD",),
    "L": ("LIVE",),
    "Lr": ("ROOF LIVE",),
    "S": ("SNOW",),
    "R": ("RAIN",),
    "W": ("WIND X", "WIND Y"),
    "E": ("EQ X", "EQ Y"),
}
"""Names of the cases :func:`missing_load_cases` proposes, per load role.

Each name is one :func:`opensees_studio.core.combinations.guess_load_role`
reads back as its role. Wind and earthquake get one case per horizontal axis.
"""


def missing_load_cases(
    code: str, roles: Mapping[str, Iterable[int]], ndm: int = 3
) -> list[tuple[str, str]]:
    """``(role, case name)`` for each load ``code`` uses that ``roles`` has no case for.

    A 2D model (``ndm == 2``, Y vertical) gets one wind and one earthquake case
    along X; a 3D model (Z vertical) one along X and one along Y.
    """
    out: list[tuple[str, str]] = []
    for role in CODES[code].roles:
        if list(roles.get(role, ())):
            continue
        names = PLACEHOLDER_CASE_NAMES[role]
        if ndm == 2:
            names = names[:1]
        out.extend((role, name) for name in names)
    return out


def generate_for_code(
    code: str,
    roles: Mapping[str, Iterable[int]],
    *,
    peak_cases: Iterable[int] = (),
    case_names: Mapping[int, str] | None = None,
    options: GeneratorOptions | None = None,
) -> list[GeneratedCombination]:
    """Run the generator of ``code`` (a key of :data:`CODES`)."""
    if code not in CODES:
        raise ValueError(f"Unknown combination code {code!r}.")
    merged = {**default_options(code), **(options or {})}
    return CODES[code].generate(
        roles, peak_cases=peak_cases, case_names=case_names or {}, options=merged
    )


def envelope_groups(
    generated: Sequence[GeneratedCombination],
) -> dict[str, list[GeneratedCombination]]:
    """The generated combinations by group, in first-seen order."""
    groups: dict[str, list[GeneratedCombination]] = {}
    for combo in generated:
        groups.setdefault(combo.group, []).append(combo)
    return groups
