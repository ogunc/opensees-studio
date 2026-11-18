"""Load combinations: factored sums and envelopes of analysis-case results.

A combination is post-processing. It never runs a solver: it takes the stored
results of analysis cases (or of other combinations) and combines them, one
scalar component at a time — every displacement and reaction DOF, every element
force component.

Every result carries an upper and a lower bound. A static case is
*single-valued* (both bounds are the same numbers); a response spectrum case is
a peak, so its bounds are ``+peak`` and ``-peak``. The four combination types
are the SAP2000 ones, with term ``k`` scaled by its factor ``f_k`` first
(``hi_k = max(f u_k, f l_k)``, ``lo_k = min(f u_k, f l_k)``):

- **Linear Add** — ``max = sum hi_k``, ``min = sum lo_k``. Single-valued when
  every term is. Superposition: valid for linear responses only.
- **Envelope** — ``max = max_k hi_k``, ``min = min_k lo_k``.
- **Absolute Add** — ``max = sum_k max(|hi_k|, |lo_k|)``, ``min = -max``.
- **SRSS** — ``max = sqrt(sum_k max(|hi_k|, |lo_k|)^2)``, ``min = -max``.

A quantity is combined only when every term provides it. A response spectrum
case provides displacements, reactions, element forces and shell resultants
(the modal combination of each), all as peaks, so its bounds are ``±peak``; a
result stored before the spectrum case had forces provides displacements only.
:func:`combine` reports what it had to leave out.

This module is part of ``core``: no Qt, no openseespy.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, get_args

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

from opensees_studio.core._base import Entity, omit_when_default

if TYPE_CHECKING:
    from opensees_studio.core.project import Project

CombinationType = Literal["LinearAdd", "Envelope", "AbsoluteAdd", "SRSS"]
COMBINATION_TYPES: tuple[str, ...] = get_args(CombinationType)

COMBINATION_LABELS: dict[str, str] = {
    "LinearAdd": "Linear Add",
    "Envelope": "Envelope",
    "AbsoluteAdd": "Absolute Add",
    "SRSS": "SRSS",
}
"""What the dialogs and result titles call each type."""

COMBINABLE_CASE_TYPES: tuple[str, ...] = ("Static", "ResponseSpectrum")
"""Analysis case types a combination can take.

A modal case has no load to scale (a mode shape's amplitude is arbitrary), and
pushover and transient cases are histories, not one state.
"""

RESULT_FIELDS: tuple[str, ...] = (
    "node_disp",
    "node_reaction",
    "element_forces",
    "element_stresses",
)
"""Quantities a combination combines, by their result attribute name."""

FIELD_LABELS: dict[str, str] = {
    "node_disp": "displacements",
    "node_reaction": "reactions",
    "element_forces": "element forces",
    "element_stresses": "shell stress resultants",
}


# ─────────────────────────── model ───────────────────────────
class CombinationTerm(BaseModel):
    """One included case (or combination) and its scale factor."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    # A term on an analysis case, the usual kind, stores no ``source``.
    serialize_without_defaults = omit_when_default("source")

    source: Literal["case", "combination"] = "case"
    """Whether :attr:`ref_id` names an analysis case or another combination."""
    ref_id: PositiveInt
    factor: float = 1.0

    @field_validator("factor")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("A scale factor must be a finite number.")
        return value


class LoadCombination(Entity):
    """A named combination of analysis-case (or combination) results."""

    combination_type: CombinationType = "LinearAdd"
    terms: list[CombinationTerm] = Field(default_factory=list)


# ─────────────────────── references ───────────────────────
def _case(project: Project, case_id: int) -> Any:
    return next((c for c in project.analyses if c.id == case_id), None)


def _combination(project: Project, combination_id: int) -> LoadCombination | None:
    return next((c for c in project.combinations if c.id == combination_id), None)


def term_label(project: Project, term: CombinationTerm) -> str:
    """``Case 'DEAD'`` / ``Combination 'ULS1'``, or the id when it is gone."""
    if term.source == "case":
        case = _case(project, term.ref_id)
        return f"case '{case.name}'" if case is not None else f"missing case {term.ref_id}"
    combo = _combination(project, term.ref_id)
    return (
        f"combination '{combo.name}'" if combo is not None else f"missing combination {term.ref_id}"
    )


def combination_problems(project: Project, combination: LoadCombination) -> list[str]:
    """Everything that stops ``combination`` from being combined (empty when it can be)."""
    problems: list[str] = []
    if not combination.terms:
        problems.append(f"Combination '{combination.name}' includes no case.")
    for term in combination.terms:
        if term.source == "case":
            case = _case(project, term.ref_id)
            if case is None:
                problems.append(
                    f"Combination '{combination.name}' refers to missing analysis case "
                    f"{term.ref_id}."
                )
            elif case.type not in COMBINABLE_CASE_TYPES:
                problems.append(
                    f"Combination '{combination.name}' includes {case.type} case "
                    f"'{case.name}': only {' and '.join(COMBINABLE_CASE_TYPES)} cases "
                    "can be combined."
                )
        elif _combination(project, term.ref_id) is None:
            problems.append(
                f"Combination '{combination.name}' refers to missing combination {term.ref_id}."
            )
    try:
        combination_order(project, combination.id)
    except ValueError as exc:
        problems.append(str(exc))
    return problems


def combination_order(project: Project, combination_id: int) -> list[int]:
    """Combination ids in the order they must be evaluated, ending with ``combination_id``.

    Raises:
        ValueError: when combinations include each other in a cycle.
    """
    order: list[int] = []
    visiting: list[int] = []

    def visit(cid: int) -> None:
        if cid in order:
            return
        if cid in visiting:
            names = [_name(c) for c in [*visiting[visiting.index(cid) :], cid]]
            raise ValueError("Combinations include each other: " + " → ".join(names) + ".")
        visiting.append(cid)
        combo = _combination(project, cid)
        for term in combo.terms if combo is not None else []:
            if term.source == "combination":
                visit(term.ref_id)
        visiting.pop()
        order.append(cid)

    def _name(cid: int) -> str:
        combo = _combination(project, cid)
        return f"'{combo.name}'" if combo is not None else str(cid)

    visit(combination_id)
    return order


def required_case_ids(project: Project, combination_id: int) -> list[int]:
    """Analysis cases ``combination_id`` needs, directly or through nested combinations.

    In first-use order, without repeats.
    """
    cases: list[int] = []
    for cid in combination_order(project, combination_id):
        combo = _combination(project, cid)
        for term in combo.terms if combo is not None else []:
            if term.source == "case" and term.ref_id not in cases:
                cases.append(term.ref_id)
    return cases


def combinations_using_case(project: Project, case_id: int) -> list[LoadCombination]:
    """Combinations that include analysis case ``case_id`` directly."""
    return [
        combo
        for combo in project.combinations
        if any(t.source == "case" and t.ref_id == case_id for t in combo.terms)
    ]


def combinations_using_combination(project: Project, combination_id: int) -> list[LoadCombination]:
    """Combinations that include combination ``combination_id`` directly."""
    return [
        combo
        for combo in project.combinations
        if any(t.source == "combination" and t.ref_id == combination_id for t in combo.terms)
    ]


def nonlinear_reasons(project: Project, case: Any) -> list[str]:
    """Why ``case`` may not respond linearly (empty when nothing points to it).

    Looks at what the case and model declare: a static solve with an iterative
    algorithm, frames with a P-Delta or corotational transformation, corotational
    trusses. Material nonlinearity is not detected.
    """
    reasons: list[str] = []
    if getattr(case, "type", None) != "Static":
        return reasons
    if case.algorithm != "Linear":
        reasons.append(f"it is solved with the {case.algorithm} algorithm")
    used = {str(getattr(el, "geom_transf", "Linear")) for el in project.elements}
    transforms = sorted(used - {"Linear"})
    if transforms:
        reasons.append(f"the model has {' and '.join(transforms)} frame transformations")
    if any(getattr(el, "type", "") == "CorotTruss" for el in project.elements):
        reasons.append("the model has corotational trusses")
    return reasons


def superposition_warnings(project: Project, combination: LoadCombination) -> list[str]:
    """Warnings for a combination that adds results of possibly nonlinear cases.

    Linear Add, Absolute Add and SRSS all add responses, which is superposition;
    an envelope only compares them and is valid for any case.
    """
    if combination.combination_type == "Envelope":
        return []
    warnings: list[str] = []
    for term in combination.terms:
        if term.source != "case":
            continue
        case = _case(project, term.ref_id)
        reasons = nonlinear_reasons(project, case) if case is not None else []
        if reasons:
            warnings.append(
                f"{COMBINATION_LABELS[combination.combination_type]} combination "
                f"'{combination.name}' adds case '{case.name}', which may be nonlinear "
                f"({'; '.join(reasons)}): superposition holds only for a linear response. "
                "Run the summed loads as one case, or use an Envelope."
            )
    return warnings


def model_fingerprint(project: Project) -> str:
    """A hash of everything an analysis result depends on.

    Two projects with the same fingerprint give the same case results, so a
    result stored under one fingerprint is current exactly while the project
    still has it. The combinations, the design check settings, and the metadata
    other than the model's units (name, author, display units), are left out:
    editing them changes no result.
    """
    data = project.model_dump(mode="json", by_alias=True, exclude={"combinations", "design"})
    data["meta"] = {"units": data["meta"]["units"]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


# ─────────────────────────── math ───────────────────────────
FieldValues = dict[int, np.ndarray]
"""Entity id → 1-D vector of components (one node's DOFs, one element's forces)."""


@dataclass
class ResponseBounds:
    """Upper and lower bound of every quantity of one case or combination.

    ``upper`` and ``lower`` map a field name (:data:`RESULT_FIELDS`) to its
    values; a field a result does not provide is absent. A single-valued result
    has the same numbers in both.
    """

    upper: dict[str, FieldValues]
    lower: dict[str, FieldValues]
    single_valued: bool = True

    @classmethod
    def single(cls, fields: dict[str, FieldValues]) -> ResponseBounds:
        """A result with one value per component (a static case)."""
        return cls(upper=fields, lower=fields, single_valued=True)

    @classmethod
    def peaks(cls, fields: dict[str, FieldValues]) -> ResponseBounds:
        """A result known only as a peak magnitude (a response spectrum case): ``±peak``."""
        upper = {name: {k: np.abs(v) for k, v in values.items()} for name, values in fields.items()}
        lower = {name: {k: -v for k, v in values.items()} for name, values in upper.items()}
        return cls(upper=upper, lower=lower, single_valued=False)


@dataclass
class CombinedResponse:
    """What :func:`combine` returns: the bounds and what had to be left out."""

    bounds: ResponseBounds
    missing_fields: list[str] = field(default_factory=list)
    """Fields some term does not provide, so the combination has none."""


def _scaled(factor: float, upper: np.ndarray, lower: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b = factor * upper, factor * lower
    return np.maximum(a, b), np.minimum(a, b)


def combine(
    combination_type: str,
    terms: Sequence[tuple[float, ResponseBounds]],
) -> CombinedResponse:
    """Combine ``(factor, bounds)`` terms with the rule of ``combination_type``.

    Each field present in every term is combined over the ids every term has
    (the same model gives the same ids); vectors of different lengths are
    combined over their common leading components. See the module docstring for
    the rules.
    """
    if combination_type not in COMBINATION_TYPES:
        raise ValueError(f"Unknown combination type: {combination_type!r}.")
    if not terms:
        raise ValueError("A combination needs at least one term.")

    single = all(b.single_valued for _, b in terms) and (
        combination_type == "LinearAdd" or (combination_type == "Envelope" and len(terms) == 1)
    )
    upper: dict[str, FieldValues] = {}
    lower: dict[str, FieldValues] = {}
    missing: list[str] = []

    for name in RESULT_FIELDS:
        if not all(name in b.upper for _, b in terms):
            # An empty field (no shells, say) is not something a term lacks.
            if any(b.upper.get(name) for _, b in terms):
                missing.append(name)
            continue
        ids = set(terms[0][1].upper[name])
        for _, b in terms[1:]:
            ids &= set(b.upper[name])
        up_field: FieldValues = {}
        lo_field: FieldValues = {}
        for key in sorted(ids):
            width = min(int(np.size(b.upper[name][key])) for _, b in terms)
            scaled = [
                _scaled(
                    f,
                    np.asarray(b.upper[name][key], dtype=float).ravel()[:width],
                    np.asarray(b.lower[name][key], dtype=float).ravel()[:width],
                )
                for f, b in terms
            ]
            hi = np.stack([s[0] for s in scaled])
            lo = np.stack([s[1] for s in scaled])
            if combination_type == "LinearAdd":
                up, down = hi.sum(axis=0), lo.sum(axis=0)
            elif combination_type == "Envelope":
                up, down = hi.max(axis=0), lo.min(axis=0)
            else:
                magnitude = np.maximum(np.abs(hi), np.abs(lo))
                if combination_type == "AbsoluteAdd":
                    up = magnitude.sum(axis=0)
                else:  # SRSS
                    up = np.sqrt((magnitude**2).sum(axis=0))
                down = -up
            up_field[key] = up
            lo_field[key] = down
        upper[name] = up_field
        lower[name] = lo_field

    return CombinedResponse(
        bounds=ResponseBounds(upper=upper, lower=upper if single else lower, single_valued=single),
        missing_fields=missing,
    )


# ──────────────────── ASCE 7-16 LRFD generator ────────────────────
LOAD_ROLES: tuple[str, ...] = ("D", "L", "Lr", "S", "R", "W", "E")
"""Load roles the ASCE 7-16 generator understands (Section 2.3.1 symbols)."""

LOAD_ROLE_LABELS: dict[str, str] = {
    "D": "Dead (D)",
    "L": "Live (L)",
    "Lr": "Roof live (Lr)",
    "S": "Snow (S)",
    "R": "Rain (R)",
    "W": "Wind (W)",
    "E": "Earthquake (E)",
}


_ROLE_NAMES: dict[str, tuple[str, ...]] = {
    "D": ("D", "DL", "DEAD", "SW", "SDL", "SELF"),
    "L": ("L", "LL", "LIVE"),
    "Lr": ("LR", "ROOF"),
    "S": ("S", "SNOW"),
    "R": ("R", "RAIN"),
    "W": ("W", "WL", "WIND"),
    "E": ("E", "EQ", "EARTHQUAKE", "SEISMIC"),
}


def guess_load_role(name: str) -> str | None:
    """The :data:`LOAD_ROLES` entry a case name suggests (``DEAD`` → ``D``, ``WX`` → ``W``).

    Matches the whole name or its leading word (``EQ-X``, ``WIND 0deg``), case
    insensitive; a trailing direction letter is ignored (``EX``, ``WY``).
    ``None`` when nothing matches.
    """
    words = "".join(ch if ch.isalnum() else " " for ch in name.upper()).split()
    if not words:
        return None
    for candidate in (words[0], words[0].rstrip("XYZ") or words[0]):
        for role, names in _ROLE_NAMES.items():
            if candidate in names:
                return role
    return None


ORTHOGONAL_FACTOR = 0.3
"""Share of the orthogonal direction in the 100%/30% earthquake rule."""

LateralVariant = tuple[tuple[float, int], ...]
"""One way a lateral load acts: ``(signed coefficient, case id)`` parts."""


def lateral_variants(
    cases: Iterable[int],
    peak_cases: Iterable[int] = (),
    *,
    orthogonal: bool = False,
) -> list[LateralVariant]:
    """The ways the lateral cases of one role act, as :data:`LateralVariant` parts.

    A lateral load acts both ways, so a static case gives a ``+1`` and a ``-1``
    variant. A case of ``peak_cases`` (a response spectrum, already ``±peak``)
    gives one: the two would be identical. With ``orthogonal`` and several
    cases, each case in turn acts at 100% with every other at 30%
    (``ORTHOGONAL_FACTOR``), each static case in both signs: ``±Ex ± 0.3Ey``
    and ``±0.3Ex ± Ey``.
    """
    peaks = set(peak_cases)
    ordered = list(dict.fromkeys(cases))
    if not orthogonal or len(ordered) < 2:
        return [
            ((sign, cid),) for cid in ordered for sign in ((1.0,) if cid in peaks else (1.0, -1.0))
        ]
    out: list[LateralVariant] = []
    for primary in ordered:
        parts = [primary, *[c for c in ordered if c != primary]]
        weight = {c: (1.0 if c == primary else ORTHOGONAL_FACTOR) for c in parts}
        free = [c for c in parts if c not in peaks]
        for signs in itertools.product((1.0, -1.0), repeat=len(free)):
            sign_of = dict(zip(free, signs, strict=True))
            out.append(tuple((sign_of.get(c, 1.0) * weight[c], c) for c in parts))
    return out


def variant_name(scale: float, variant: LateralVariant, token: Callable[[int], str]) -> str:
    """``+0.5W``, ``-E3``, ``+E1-0.3E2``: ``variant`` times ``scale``, each part signed."""
    pieces = []
    for coef, cid in variant:
        value = round(coef * scale, 10)
        magnitude = "" if abs(value) == 1.0 else f"{abs(value):g}"
        pieces.append(f"{'+' if value > 0 else '-'}{magnitude}{token(cid)}")
    return "".join(pieces)


def scaled_parts(scale: float, variant: LateralVariant) -> list[tuple[float, list[int]]]:
    """``variant`` times ``scale`` as ``(factor, [case id])`` groups for a term builder."""
    return [(scale * coef, [cid]) for coef, cid in variant]


def asce7_16_lrfd(
    roles: Mapping[str, Iterable[int]],
    *,
    peak_cases: Iterable[int] = (),
    orthogonal: bool = False,
) -> list[tuple[str, list[CombinationTerm]]]:
    """ASCE 7-16 Section 2.3.1 basic LRFD combinations, as ``(name, terms)`` pairs.

    ``roles`` maps a role of :data:`LOAD_ROLES` to the analysis cases carrying
    that load. Every dead case enters each combination; ``Lr or S or R`` gives
    one combination per role present; each wind and each earthquake case gives
    one combination per sign, since a lateral load acts both ways (see
    :func:`lateral_variants`; ``orthogonal`` applies the 100%/30% rule to the
    earthquake cases). A
    combination is produced only when every load it names is present (and
    ``D`` is always required). The live-load factor 1.0 in combinations 3 to 5
    is used as is: the 0.5 reduction of the standard's exception depends on the
    occupancy and is left to the engineer. A case of ``peak_cases`` (a response
    spectrum, whose result is already ``±peak``) gets one combination, not one
    per sign: the two would be identical.

    1. 1.4D
    2. 1.2D + 1.6L + 0.5(Lr or S or R)
    3. 1.2D + 1.6(Lr or S or R) + (L or 0.5W)
    4. 1.2D + 1.0W + L + 0.5(Lr or S or R)
    5. 1.2D + 1.0E + L + 0.2S
    6. 0.9D + 1.0W
    7. 0.9D + 1.0E
    """
    by_role = {role: list(dict.fromkeys(roles.get(role, ()))) for role in LOAD_ROLES}
    dead = by_role["D"]
    if not dead:
        return []
    live = by_role["L"]
    roof = [(r, cid) for r in ("Lr", "S", "R") for cid in by_role[r]]
    peaks = list(peak_cases)
    lateral_w = lateral_variants(by_role["W"], peaks)
    lateral_e = lateral_variants(by_role["E"], peaks, orthogonal=orthogonal)

    out: list[tuple[str, list[CombinationTerm]]] = []

    def terms(*groups: tuple[float, Iterable[int]]) -> list[CombinationTerm]:
        merged: dict[int, float] = {}
        for factor, ids in groups:
            for cid in ids:
                merged[cid] = merged.get(cid, 0.0) + factor
        return [CombinationTerm(ref_id=cid, factor=f) for cid, f in merged.items()]

    def load(role: str, cid: int) -> str:
        """``W``, or ``W3`` when several cases carry the role."""
        return f"{role}{cid}" if len(by_role[role]) > 1 else role

    def signed(scale: float, role: str, variant: LateralVariant) -> str:
        return variant_name(scale, variant, lambda cid: load(role, cid))

    with_live = "+L" if live else ""

    # 1. 1.4D
    out.append(("1.4D", terms((1.4, dead))))
    # 2. 1.2D + 1.6L + 0.5(Lr or S or R)
    if live and roof:
        for role, cid in roof:
            out.append(
                (
                    f"1.2D+1.6L+0.5{load(role, cid)}",
                    terms((1.2, dead), (1.6, live), (0.5, [cid])),
                )
            )
    elif live:
        out.append(("1.2D+1.6L", terms((1.2, dead), (1.6, live))))
    # 3. 1.2D + 1.6(Lr or S or R) + (L or 0.5W)
    for role, cid in roof:
        out.append(
            (
                f"1.2D+1.6{load(role, cid)}{with_live}",
                terms((1.2, dead), (1.6, [cid]), (1.0, live)),
            )
        )
        for w in lateral_w:
            out.append(
                (
                    f"1.2D+1.6{load(role, cid)}{signed(0.5, 'W', w)}",
                    terms((1.2, dead), (1.6, [cid]), *scaled_parts(0.5, w)),
                )
            )
    # 4. 1.2D + 1.0W + L + 0.5(Lr or S or R)
    for w in lateral_w:
        w_name = signed(1.0, "W", w)
        if not roof:
            out.append(
                (f"1.2D{w_name}{with_live}", terms((1.2, dead), *scaled_parts(1.0, w), (1.0, live)))
            )
        for role, cid in roof:
            out.append(
                (
                    f"1.2D{w_name}{with_live}+0.5{load(role, cid)}",
                    terms((1.2, dead), *scaled_parts(1.0, w), (1.0, live), (0.5, [cid])),
                )
            )
    # 5. 1.2D + 1.0E + L + 0.2S
    snow = by_role["S"]
    for e in lateral_e:
        out.append(
            (
                f"1.2D{signed(1.0, 'E', e)}{with_live}{'+0.2S' if snow else ''}",
                terms((1.2, dead), *scaled_parts(1.0, e), (1.0, live), (0.2, snow)),
            )
        )
    # 6. 0.9D + 1.0W
    for w in lateral_w:
        out.append((f"0.9D{signed(1.0, 'W', w)}", terms((0.9, dead), *scaled_parts(1.0, w))))
    # 7. 0.9D + 1.0E
    for e in lateral_e:
        out.append((f"0.9D{signed(1.0, 'E', e)}", terms((0.9, dead), *scaled_parts(1.0, e))))
    return out
