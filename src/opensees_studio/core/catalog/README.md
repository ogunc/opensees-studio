# core/catalog — GiD schema catalog

This package contains **auto-generated Pydantic v2 schema descriptions** for
all OpenSees materials and conditions defined in the
[gidopensees](https://github.com/rclab-auth/gidopensees) GiD preprocessor.

## Public import surface

```python
from opensees_studio.core.catalog import CATALOG

# Look up a Spec class by its gidopensees name
Steel02Spec = CATALOG["Steel02"]
spec = Steel02Spec()          # instantiate with defaults
spec.model_dump_json()        # serialize
```

`CATALOG` is a `dict[str, type[BaseModel]]` mapping every material's
gidopensees name (e.g. `"Steel02"`) to its generated `Spec` class.
It contains exactly 58 entries (one per material in `OpenSees.mat`).

Per-book discriminated Union types are available in `generated/__init__.py`:

```python
from opensees_studio.core.catalog.generated import UniaxialSteelMaterials
```

Condition specs live under `generated/conditions/`.

## Regenerating

Run the codegen tool any time the upstream `schemas.json` changes:

```bash
python -m tools.gidopensees_import.codegen \
    --schemas tools/gidopensees_import/schemas.json \
    --out src/opensees_studio/core/catalog/generated/
```

## Do not hand-edit `generated/`

Files under `generated/` are overwritten on each codegen run.
Hand-curated overrides, corrections, or extensions belong in
`curated/` (currently empty — reserved for future use).

## Scope note

Catalog Spec classes are **schema descriptions only**. They capture the
field names, types, defaults, and UI metadata from the gidopensees
definition files. They are **not yet wired into the OpenSees runtime**.
The mapping from a `Spec` to an actual `uniaxialMaterial` call is a
future deliverable tracked in the ADR.

## Attribution

Schema data from [gidopensees](https://github.com/rclab-auth/gidopensees),
Copyright (C) Reinforced Concrete Laboratory, Aristotle University of
Thessaloniki (AUTh), licensed under GNU GPL-3.0. Combined here under
AGPL-3.0 per GPL section 13.

`CATALOG` exposes the 58 material specs only; condition specs are intentionally
kept in a separate namespace (`generated/conditions/`, 39 specs) so that
material and boundary-condition objects remain independently importable and
do not pollute each other's namespace.
