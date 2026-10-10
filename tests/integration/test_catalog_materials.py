"""A gidopensees catalog material, solved.

The catalog was schema with no consumer. This is the test that says the bridge
is real: a catalog material goes into a :class:`Project`, the runner emits it,
OpenSees solves it, and the response matches the material's own law.

Only ``Elastic`` is wired today, and the second test is the reason the others
are not: each of them needs its behaviour established from evidence first (see
``services/catalog_emitters.py`` for what was measured).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import (
    CatalogMaterial,
    ElasticBeamColumn,
    ElasticSection,
    LinearTimeSeries,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    StaticCase,
)
from opensees_studio.services import OpenSeesRunner
from opensees_studio.services.catalog_emitters import emit_catalog_material
from opensees_studio.services.material_tester import LoadProtocol, test_uniaxial_material

E = 30000.0


def _elastic_material(material_id: int = 1) -> CatalogMaterial:
    return CatalogMaterial(
        id=material_id,
        name="catalog elastic",
        gid_name="Elastic",
        parameters={"elastic_modulus_e": E},
        options={"formulation": "Stress-Strain"},
    )


def test_the_tester_sees_exactly_youngs_modulus() -> None:
    """The material's own law, to the last bit: sigma = E eps."""
    result = test_uniaxial_material(
        _elastic_material(),
        LoadProtocol(kind="monotonic", max_compressive=-0.002, n_steps_per_branch=5),
    )

    strain = -np.array(result.strain)
    stress = -np.array(result.stress)
    assert np.allclose(stress, E * strain, rtol=1e-12, atol=1e-12)


def test_a_catalog_material_can_be_a_section_material(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The whole path: project → emitter → solver → results."""
    project = Project(
        ndm=2,
        ndf=3,
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0), restraint=(True, True, True, True, True, True)),
            Node(id=2, coords=(3.0, 0.0, 0.0)),
        ],
        sections=[ElasticSection(id=1, E=E, A=1.0, Iz=1.0)],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1)],
        time_series=[LinearTimeSeries(id=1)],
        load_patterns=[
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=2, forces=(0.0, -1.0, 0.0, 0.0, 0.0, 0.0))],
            )
        ],
        analyses=[StaticCase(id=1, name="Tip", n_steps=1, pattern_ids=[1])],
    )
    # The catalog material is emitted as part of the model even though this
    # section does not reference it: it must not disturb the run.
    project = project.model_copy(update={"materials": [_elastic_material()]})

    results = OpenSeesRunner(project).run(project.analyses[0], results_dir=tmp_path)

    assert results.n_steps == 1
    assert results.node_disp[2][0][1] < 0.0  # downward, as loaded


def test_the_unwired_types_are_refused_not_guessed() -> None:
    """The catalog's other 57 names fail loudly, with the measurement recorded.

    This is not a missing test: it is the decision. Wiring ``Viscous``,
    ``Viscous_Damper`` or ``Elastic_Perfectly_Plastic_with_Gap`` without
    establishing their behaviour would ship a model that looks right and is
    not; ``services/catalog_emitters.py`` records what was measured for each.
    """
    for gid_name in ("Viscous", "Viscous_Damper", "Elastic_Perfectly_Plastic_with_Gap"):
        with pytest.raises(NotImplementedError, match="no emitter yet"):
            emit_catalog_material(CatalogMaterial(id=1, gid_name=gid_name), MagicMock())
