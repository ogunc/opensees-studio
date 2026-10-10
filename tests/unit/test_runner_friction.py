"""OpenSeesRunner emission of friction models (live 3.8.0 argument order)."""

from __future__ import annotations

from unittest.mock import MagicMock, call

from opensees_studio.core import (
    CoulombFriction,
    ElasticUniaxial,
    Project,
    VelDependentFriction,
    VelNormalFrcDepFriction,
)
from opensees_studio.services import OpenSeesRunner


def test_friction_models_follow_the_materials() -> None:
    project = Project(
        ndm=2,
        ndf=3,
        materials=[ElasticUniaxial(id=1, E=1e5)],
        friction_models=[
            CoulombFriction(id=1, mu=0.1),
            VelDependentFriction(id=2, mu_slow=0.05, mu_fast=0.1, trans_rate=0.5),
            VelNormalFrcDepFriction(
                id=3,
                a_slow=0.1,
                n_slow=-0.1,
                a_fast=0.2,
                n_fast=-0.2,
                alpha0=0.5,
                alpha1=1.0,
                alpha2=0.0,
                max_mu_fact=1.5,
            ),
        ],
    )
    ops = MagicMock()
    OpenSeesRunner(project, ops_module=ops).build()
    names = [c[0] for c in ops.method_calls]
    assert names.index("uniaxialMaterial") < names.index("frictionModel")
    friction_calls = [c for c in ops.method_calls if c[0] == "frictionModel"]
    assert friction_calls == [
        call.frictionModel("Coulomb", 1, 0.1),
        call.frictionModel("VelDependent", 2, 0.05, 0.1, 0.5),
        call.frictionModel("VelNormalFrcDep", 3, 0.1, -0.1, 0.2, -0.2, 0.5, 1.0, 0.0, 1.5),
    ]
