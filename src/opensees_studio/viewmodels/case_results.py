"""Results of every case run in this session, for load combinations.

The window shows one result at a time, but a combination needs several. Each
static or response spectrum result that comes back from a run is kept here
with the fingerprint of the model it was computed on
(:func:`opensees_studio.core.combinations.model_fingerprint`); a result counts
as current only while the project still has that fingerprint, so an edit to the
model makes every stored result stale at once while adding or editing a
combination does not.
"""

from __future__ import annotations

from typing import Any

from opensees_studio.core import Project
from opensees_studio.core.combinations import model_fingerprint, required_case_ids
from opensees_studio.services.combination import combine_results
from opensees_studio.services.results import (
    CombinationResults,
    ResponseSpectrumResults,
    StaticResults,
)

COMBINABLE_RESULTS = (StaticResults, ResponseSpectrumResults)


class CaseResultsCache:
    """Case id → (model fingerprint, results) for the combinable result kinds."""

    def __init__(self) -> None:
        self._entries: dict[int, tuple[str, Any]] = {}

    def put(self, project: Project, results: Any) -> bool:
        """Keep ``results`` as current for ``project``; False for a kind no combination takes."""
        if not isinstance(results, COMBINABLE_RESULTS):
            return False
        self._entries[results.case_id] = (model_fingerprint(project), results)
        return True

    def clear(self) -> None:
        self._entries.clear()

    def current(self, project: Project) -> dict[int, Any]:
        """Results computed on the project as it is now, by case id."""
        if not self._entries:
            return {}
        fingerprint = model_fingerprint(project)
        return {cid: r for cid, (fp, r) in self._entries.items() if fp == fingerprint}

    def missing_cases(self, project: Project, combination_id: int) -> list[int]:
        """Cases ``combination_id`` needs that have no current result (in run order)."""
        have = self.current(project)
        return [cid for cid in required_case_ids(project, combination_id) if cid not in have]

    def combine(self, project: Project, combination_id: int) -> CombinationResults:
        """Evaluate ``combination_id`` from the current results.

        Raises the errors of :func:`~opensees_studio.services.combination.combine_results`.
        """
        return combine_results(project, combination_id, self.current(project))
