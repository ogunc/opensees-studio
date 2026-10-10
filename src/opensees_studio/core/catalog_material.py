"""A material described by the gidopensees catalog instead of a hand-written class.

The catalog carries a Pydantic Spec for every material gidopensees knows about
(58 of them, generated into ``core/catalog/generated``). Those Specs are
schema: field names, defaults with units, UI dependencies. This model is the
bridge — it puts one of those materials into a :class:`~opensees_studio.core.Project`
so the runner can emit it.

The bridge is deliberately **narrow**. A Spec is not an OpenSees signature:
half its fields are UI discriminators (``formulation``, ``material_type``,
``steel_grade``) and the physical ones are text with units, so emitting
positionally from a Spec would be guesswork that produces *wrong models rather
than errors*. Each gidopensees name is therefore wired one at a time, by hand,
against the live solver (see ``services/catalog_emitters.py``), and an
unwired name fails loudly.

Validation of the name and the parameter keys imports the catalog lazily:
nothing pays for 58 generated modules until a catalog material is actually
created.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from opensees_studio.core._base import Entity


def catalog_spec(gid_name: str) -> type[Any] | None:
    """The generated Spec class for a gidopensees name, or None if unknown."""
    from opensees_studio.core.catalog import CATALOG

    return CATALOG.get(gid_name)


def catalog_names() -> list[str]:
    """Every gidopensees material name the catalog carries, sorted."""
    from opensees_studio.core.catalog import CATALOG

    return sorted(CATALOG)


class CatalogMaterial(Entity):
    """A material from the gidopensees catalog.

    ``parameters`` holds the values the emitter needs, **in the project's unit
    system**: the application never converts (see ``core.units``), so the
    engineer enters values in the units the model is built in. The schema's own
    text defaults are a starting point for the UI, not a conversion table.

    ``options`` carries the string discriminators an emitter may need, such as
    the stress-strain/force-deformation/moment-rotation choice of
    ``Elastic_Perfectly_Plastic_with_Gap``.
    """

    type: Literal["Catalog"] = "Catalog"
    gid_name: str = Field(..., min_length=1, description="Key in the gidopensees catalog.")
    parameters: dict[str, float] = Field(default_factory=dict)
    options: dict[str, str] = Field(default_factory=dict)

    @field_validator("gid_name")
    @classmethod
    def _known_name(cls, value: str) -> str:
        if catalog_spec(value) is None:
            raise ValueError(
                f"{value!r} is not a gidopensees catalog material. "
                f"Known names: {', '.join(catalog_names()[:8])}, …"
            )
        return value

    @field_validator("parameters")
    @classmethod
    def _parameters_belong_to_the_spec(cls, value: dict[str, float], info: Any) -> dict[str, float]:
        name = info.data.get("gid_name")
        spec = catalog_spec(name) if name else None
        if spec is None:
            return value
        unknown = sorted(set(value) - set(spec.model_fields))
        if unknown:
            raise ValueError(
                f"{name} has no field(s) {', '.join(unknown)}; "
                f"its schema has {', '.join(sorted(spec.model_fields))}"
            )
        return value

    @classmethod
    def from_schema_defaults(cls, gid_name: str, id: int, name: str = "") -> CatalogMaterial:
        """Build one from the Spec's own defaults, reading the numbers out of them.

        Fields whose default is not a number (a discriminator, or a text
        default the parser cannot read) are left out; the emitter reports what
        it still needs.
        """
        from opensees_studio.core.quantities import QuantityError, parse_quantity

        spec = catalog_spec(gid_name)
        if spec is None:
            raise ValueError(f"{gid_name!r} is not a gidopensees catalog material.")
        parameters: dict[str, float] = {}
        options: dict[str, str] = {}
        for field_name, field in spec.model_fields.items():
            default = field.default
            if isinstance(default, str):
                try:
                    parameters[field_name] = parse_quantity(default)
                except QuantityError:
                    options[field_name] = default
            elif isinstance(default, (int, float)) and not isinstance(default, bool):
                parameters[field_name] = float(default)
        return cls(
            id=id, name=name or gid_name, gid_name=gid_name, parameters=parameters, options=options
        )
