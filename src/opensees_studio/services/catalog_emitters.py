"""Curated gidopensees-name → OpenSees-command mappings.

The catalog's Specs are schema, not signatures: a Spec mixes UI discriminators
with physical parameters, several of which are text with units, and one
gidopensees object can map to different argument triples depending on a
formulation field. Emitting positionally from a Spec would therefore produce
*wrong models instead of errors*, which is worse than not supporting the type.

So each name is wired here by hand, with the command and the exact argument
order confirmed against the live solver, and the emitters are covered by tests
that run the material (``tests/integration/test_catalog_materials.py``).

A name that is in the catalog but not wired here fails loudly, naming what is
missing and what is already available. The gap analysis
(``docs/gap-analysis-gidopensees.md``) is where the remaining ones are tracked.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from opensees_studio.core import CatalogMaterial

#: Returns ``(open_sees_command, positional_args)`` for a catalog material.
CatalogEmitter = Callable[[CatalogMaterial], tuple[str, list[Any]]]

CATALOG_EMITTERS: dict[str, CatalogEmitter] = {}


def catalog_emitter(gid_name: str) -> Callable[[CatalogEmitter], CatalogEmitter]:
    """Register the emitter for a gidopensees material name."""

    def _register(func: CatalogEmitter) -> CatalogEmitter:
        if gid_name in CATALOG_EMITTERS:
            raise RuntimeError(f"two catalog emitters registered for {gid_name!r}")
        CATALOG_EMITTERS[gid_name] = func
        return func

    return _register


def wired_names() -> list[str]:
    """The gidopensees names that can actually be analysed, sorted."""
    return sorted(CATALOG_EMITTERS)


def _required(material: CatalogMaterial, *names: str) -> list[float]:
    """The named parameters, or a message saying which one is missing."""
    missing = [name for name in names if name not in material.parameters]
    if missing:
        raise ValueError(
            f"{material.gid_name} needs {', '.join(missing)}; "
            f"it has {', '.join(sorted(material.parameters)) or 'nothing'}."
        )
    return [material.parameters[name] for name in names]


def emit_catalog_material(material: CatalogMaterial, ops: Any) -> None:
    """Emit a catalog material, or explain why this one cannot be emitted yet."""
    func = CATALOG_EMITTERS.get(material.gid_name)
    if func is None:
        raise NotImplementedError(
            f"The gidopensees material {material.gid_name!r} is in the catalog but has no "
            f"emitter yet, so it cannot be analysed. Wired today: {', '.join(wired_names())}. "
            "Adding one means confirming the argument order against the solver and "
            "registering it here (see services/catalog_emitters.py)."
        )
    command, args = func(material)
    ops.uniaxialMaterial(command, material.id, *args)


# ─────────────────────── wired types ───────────────────────
# One type is wired, and it is wired because its behaviour was measured, not
# because its name looked easy. Three others in this family were probed and are
# deliberately left out until someone can state their law from evidence:
#
#   Viscous          ``uniaxialMaterial Viscous tag C alpha`` is accepted, but
#                    with the elements this application builds (zeroLength,
#                    frame) it contributes nothing: a ramped SDOF gave the same
#                    response with C = 0, 50 and 100, and an imposed-velocity
#                    zeroLength hard-exited OpenSees. The rate never reaches the
#                    material.
#   Viscous_Damper   Same element question, same answer needed first.
#   Elastic_Perfectly_Plastic_with_Gap
#                    The signature is `tag E Fy gap <eta>` (OpenSeesPy docs).
#                    Measured through the material tester and through an
#                    imposed-displacement zeroLength, the response does not
#                    follow the field names: with gap = +0.002 it is zero in
#                    both directions, and with gap = -0.002 the compression
#                    force peaks at half the yield strain and falls to zero at
#                    the yield strain. Emitting it without understanding that
#                    would put a wrong model in a user's file.
#
# Each of those is one investigation away from being wired here; the emitters
# below are the shape the next one should take.


@catalog_emitter("Elastic")
def _elastic(material: CatalogMaterial) -> tuple[str, list[Any]]:
    """``uniaxialMaterial Elastic tag E`` — the bridge's verified type.

    The gidopensees object carries one physical parameter per formulation; the
    stress-strain one is the elastic modulus, and the emitter reads it from the
    ``elastic_modulus_e`` field. Verified against the solver: the tester's
    monotonic protocol gives exactly ``sigma = E * eps``
    (``tests/integration/test_catalog_materials.py``).
    """
    return "Elastic", _required(material, "elastic_modulus_e")
