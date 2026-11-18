"""Evaluate load combinations from stored analysis-case results.

The math lives in :mod:`opensees_studio.core.combinations`; this module turns
result objects into its bounds and back. Nothing here runs OpenSees: the case
results come from earlier runs (``services.result_store.load_results``).

Element forces are combined as internal forces. OpenSees ``localForce`` reports
the end-j half of a two-node element with the sign of the force *on* the
element, so a diagram reverses it (``extract_diagram_data``); the combination
does the same before taking a maximum or minimum, otherwise the "max" diagram
would draw the end-j minimum. A sum is unaffected either way.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from opensees_studio.core import Project
from opensees_studio.core.combinations import (
    FIELD_LABELS,
    RESULT_FIELDS,
    CombinedResponse,
    ResponseBounds,
    combination_order,
    combination_problems,
    combine,
    required_case_ids,
    superposition_warnings,
)
from opensees_studio.services.results import (
    CombinationResults,
    ResponseSpectrumResults,
    StaticResults,
)

CombinableResults = StaticResults | ResponseSpectrumResults


class MissingCaseResultsError(LookupError):
    """The combination needs cases that have no current results."""

    def __init__(self, combination_name: str, case_ids: list[int]) -> None:
        self.case_ids = list(case_ids)
        super().__init__(
            f"Combination '{combination_name}' needs results of case(s) "
            f"{', '.join(str(c) for c in self.case_ids)}: run them first."
        )


def _two_node_ids(project: Project) -> set[int]:
    return {el.id for el in project.elements if len(el.nodes) == 2}


def _flip_end_j(forces: dict[int, np.ndarray], two_node: set[int]) -> dict[int, np.ndarray]:
    """Reverse the end-j half of each two-node element's force vector.

    Its own inverse: applied to ``localForce`` it gives internal forces, applied
    to internal forces it gives ``localForce`` back.
    """
    out: dict[int, np.ndarray] = {}
    for eid, vec in forces.items():
        vec = np.asarray(vec, dtype=float).copy()
        if eid in two_node and vec.size % 2 == 0:
            vec[vec.size // 2 :] *= -1.0
        out[eid] = vec
    return out


def case_bounds(project: Project, results: CombinableResults) -> ResponseBounds:
    """The bounds of one case's results: final step of a static case, ``±peak`` of a spectrum.

    A spectrum gives every field it holds as a peak magnitude (displacements,
    reactions, element forces, shell resultants): the bounds are ``+peak`` and
    ``-peak``.
    """
    if isinstance(results, StaticResults):
        fields: dict[str, dict[int, np.ndarray]] = {}
        for name in RESULT_FIELDS:
            values = getattr(results, name)
            fields[name] = {k: np.atleast_2d(v)[-1].astype(float) for k, v in values.items()}
        fields["element_forces"] = _flip_end_j(fields["element_forces"], _two_node_ids(project))
        return ResponseBounds.single(fields)
    if isinstance(results, ResponseSpectrumResults):
        # A field a stored result lacks (one written before reactions and
        # element forces existed) is left out, and the combination reports it.
        fields = {
            name: {k: np.asarray(v, dtype=float) for k, v in values.items()}
            for name, values in (
                ("node_disp", results.combined_disp),
                ("node_reaction", results.node_reaction),
                ("element_forces", results.element_forces),
                ("element_stresses", results.element_stresses),
            )
            if values
        }
        return ResponseBounds.peaks(fields)
    raise TypeError(
        f"{type(results).__name__} cannot be combined: only static and response spectrum "
        "results can."
    )


def _static_bound(
    project: Project,
    combination_id: int,
    name: str,
    fields: dict[str, dict[int, np.ndarray]],
) -> StaticResults:
    """One bound as a one-step :class:`StaticResults` (forces back to ``localForce``)."""
    per_field = {
        key: {k: np.asarray(v, dtype=float).reshape(1, -1) for k, v in fields.get(key, {}).items()}
        for key in RESULT_FIELDS
    }
    per_field["element_forces"] = {
        k: v.reshape(1, -1)
        for k, v in _flip_end_j(
            {k: v.ravel() for k, v in per_field["element_forces"].items()},
            _two_node_ids(project),
        ).items()
    }
    return StaticResults(case_id=combination_id, case_name=name, n_steps=1, **per_field)


def combine_results(
    project: Project,
    combination_id: int,
    case_results: Mapping[int, CombinableResults],
) -> CombinationResults:
    """Evaluate combination ``combination_id`` from ``case_results`` (case id → results).

    Nested combinations are evaluated first, in dependency order.

    Raises:
        ValueError: the combination cannot be combined (a missing or
            non-combinable case, no terms, a cycle).
        MissingCaseResultsError: a case it needs has no entry in ``case_results``.
    """
    target = project.combination(combination_id)
    problems: list[str] = []
    order = []
    try:
        order = combination_order(project, combination_id)
    except ValueError as exc:
        problems.append(str(exc))
    existing = {c.id for c in project.combinations}
    for cid in order or [combination_id]:
        # A missing nested combination is reported by the one that includes it.
        if cid in existing:
            problems.extend(combination_problems(project, project.combination(cid)))
    if problems:
        raise ValueError("\n".join(dict.fromkeys(problems)))

    needed = required_case_ids(project, combination_id)
    missing = [cid for cid in needed if cid not in case_results]
    if missing:
        raise MissingCaseResultsError(target.name, missing)

    case_bound = {cid: case_bounds(project, case_results[cid]) for cid in needed}
    combo_response: dict[int, CombinedResponse] = {}
    warnings: list[str] = []
    for cid in order:
        combo = project.combination(cid)
        terms = [
            (
                term.factor,
                case_bound[term.ref_id]
                if term.source == "case"
                else combo_response[term.ref_id].bounds,
            )
            for term in combo.terms
        ]
        response = combine(combo.combination_type, terms)
        combo_response[cid] = response
        warnings.extend(superposition_warnings(project, combo))
        if response.missing_fields:
            listed = ", ".join(FIELD_LABELS[f] for f in response.missing_fields)
            warnings.append(
                f"Combination '{combo.name}' has no {listed}: an included case does not provide "
                "them (a response spectrum result stored before it had forces: run the case again)."
            )
    for cid in needed:
        results = case_results[cid]
        if isinstance(results, ResponseSpectrumResults):
            warnings.extend(results.warnings)

    final = combo_response[combination_id]
    bounds = final.bounds
    return CombinationResults(
        combination_id=target.id,
        combination_name=target.name,
        combination_type=target.combination_type,
        max=_static_bound(project, target.id, f"{target.name} (max)", bounds.upper),
        min=_static_bound(project, target.id, f"{target.name} (min)", bounds.lower),
        single_valued=bounds.single_valued,
        case_ids=needed,
        missing_fields=list(final.missing_fields),
        warnings=list(dict.fromkeys(warnings)),
    )
