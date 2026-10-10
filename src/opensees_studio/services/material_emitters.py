"""How each material becomes an OpenSees command.

The runner used to carry one ``match`` statement with every material's argument
assembly in it. That works, but it makes adding a material an edit to the
runner, and it leaves the gidopensees catalog — 58 generated schemas — with
nowhere to plug in. This module is the plug: an emitter registry keyed by the
material's ``type`` discriminator.

``services/catalog_emitters.py`` registers the catalog-backed materials into
the same shape; ``emit_material`` dispatches to either.

Nothing here changed behaviour: the bodies are the argument assembly that was
in ``OpenSeesRunner._emit_material``, moved. ``tests/unit/test_runner_translation.py``
drives them through a mock ``ops`` and is what proves the commands are
unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opensees_studio.core import (
    Concrete01,
    Concrete02,
    Concrete04,
    ElasticIsotropic,
    ElasticPP,
    ElasticUniaxial,
    Hardening,
    HystereticMaterial,
    HystereticSM,
    Steel01,
    Steel02,
)

#: An emitter writes one material into ``ops`` (the runner passes
#: ``openseespy.opensees`` or, for the script export, a recorder).
MaterialEmitter = Callable[[Any, Any], None]

EMITTERS: dict[str, MaterialEmitter] = {}


def emitter(type_name: str) -> Callable[[MaterialEmitter], MaterialEmitter]:
    """Register the emitter for a material ``type`` discriminator."""

    def _register(func: MaterialEmitter) -> MaterialEmitter:
        if type_name in EMITTERS:
            raise RuntimeError(f"two emitters registered for {type_name!r}")
        EMITTERS[type_name] = func
        return func

    return _register


def emit_material(material: Any, ops: Any) -> None:
    """Emit ``material`` into ``ops``; raise for a type with no emitter."""
    func = EMITTERS.get(material.type)
    if func is None:
        raise NotImplementedError(f"Material type not yet handled: {type(material).__name__}")
    func(material, ops)


# ─────────────────────── uniaxial ───────────────────────
@emitter("Elastic")
def _elastic(mat: ElasticUniaxial, ops: Any) -> None:
    args: list[Any] = [mat.E]
    if mat.eta or mat.Eneg is not None:
        args.append(mat.eta)
    if mat.Eneg is not None:
        args.append(mat.Eneg)
    ops.uniaxialMaterial("Elastic", mat.id, *args)


@emitter("Steel01")
def _steel01(mat: Steel01, ops: Any) -> None:
    args = [mat.Fy, mat.E0, mat.b]
    if mat.a1 is not None:
        args.extend([mat.a1, mat.a2, mat.a3, mat.a4])
    ops.uniaxialMaterial("Steel01", mat.id, *args)


@emitter("Steel02")
def _steel02(mat: Steel02, ops: Any) -> None:
    ops.uniaxialMaterial("Steel02", mat.id, mat.Fy, mat.E0, mat.b, mat.R0, mat.cR1, mat.cR2)


@emitter("Concrete01")
def _concrete01(mat: Concrete01, ops: Any) -> None:
    ops.uniaxialMaterial("Concrete01", mat.id, mat.fpc, mat.epsc0, mat.fpcu, mat.epsU)


@emitter("Concrete02")
def _concrete02(mat: Concrete02, ops: Any) -> None:
    ops.uniaxialMaterial(
        "Concrete02",
        mat.id,
        mat.fpc,
        mat.epsc0,
        mat.fpcu,
        mat.epsU,
        mat.lambda_,
        mat.ft,
        mat.Ets,
    )


@emitter("Concrete04")
def _concrete04(mat: Concrete04, ops: Any) -> None:
    args = [mat.fpc, mat.epsc0, mat.epscu, mat.Ec]
    if mat.fct is not None:
        args.extend([mat.fct, mat.et])
        if mat.beta is not None:
            args.append(mat.beta)
    ops.uniaxialMaterial("Concrete04", mat.id, *args)


@emitter("ElasticPP")
def _elastic_pp(mat: ElasticPP, ops: Any) -> None:
    args = [mat.E, mat.epsy_pos]
    if mat.epsy_neg is not None or mat.eps0 != 0.0:
        args.append(mat.epsy_neg if mat.epsy_neg is not None else -mat.epsy_pos)
        args.append(mat.eps0)
    ops.uniaxialMaterial("ElasticPP", mat.id, *args)


@emitter("Hardening")
def _hardening(mat: Hardening, ops: Any) -> None:
    args: list[Any] = [mat.E, mat.sigmaY, mat.H_iso, mat.H_kin]
    if mat.eta:
        args.append(mat.eta)
    ops.uniaxialMaterial("Hardening", mat.id, *args)


@emitter("Hysteretic")
def _hysteretic(mat: HystereticMaterial, ops: Any) -> None:
    ops.uniaxialMaterial(
        "Hysteretic",
        mat.id,
        mat.s1p,
        mat.e1p,
        mat.s2p,
        mat.e2p,
        mat.s3p,
        mat.e3p,
        mat.s1n,
        mat.e1n,
        mat.s2n,
        mat.e2n,
        mat.s3n,
        mat.e3n,
        mat.px,
        mat.py,
        mat.d1,
        mat.d2,
        mat.beta,
    )


@emitter("HystereticSM")
def _hysteretic_sm(mat: HystereticSM, ops: Any) -> None:
    # uniaxialMaterial HystereticSM $tag -posEnv f1 d1 f2 d2 ...
    #                                     <-negEnv f1 d1 ...>
    # Envelopes carry (force, deformation) pairs in command order.
    args: list[Any] = ["-posEnv"]
    for force, defo in mat.pos_env:
        args.extend([force, defo])
    if mat.neg_env:
        args.append("-negEnv")
        for force, defo in mat.neg_env:
            args.extend([force, defo])
    ops.uniaxialMaterial("HystereticSM", mat.id, *args)


# ─────────────────────── nD ───────────────────────
@emitter("ElasticIsotropic")
def _elastic_isotropic(mat: ElasticIsotropic, ops: Any) -> None:
    ops.nDMaterial("ElasticIsotropic", mat.id, mat.E, mat.nu, mat.rho)
