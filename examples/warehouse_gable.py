"""Build a steel warehouse with the parametric generator of the Warehouse Wizard.

Run from the repository root:

    python examples/warehouse_gable.py

Produces ``examples/warehouse_gable.osmodel``: a 20 m x 30 m gable warehouse,
six pinned-base portal frames at 6 m, purlins and girts at 1.5 m, X bracing in
the two end bays, and the RNC-07 roof loads and combinations. It is what
Define → Create Warehouse builds with these numbers:

- **Geometry** — one 20 m nave, eave at 6 m, 10 % slope (ridge at 7 m).
- **Purlins** — every second one has a stabilising angle to the rafter's bottom
  flange, so the steel check takes the rafter's unbraced length as two purlin
  spaces (2.87 m) instead of the whole slope (10.05 m). The girts have none:
  the side columns are unbraced over their 6 m.
- **Loads** — 0.10 kN/m² of cladding in DEAD (with the self weight), and in
  LIVE the RNC-07 Art. 11 light roof: 10 kg/m² plus 200 kg at each ridge.
- **Combinations** — RNC-07 Art. 15: 1.4CM, 1.2CM + 1.6CV and their envelope.

Open it and run the two cases, then Design → Steel Frame Check: the Lb column
shows the unbraced lengths the generator wrote.
"""

from __future__ import annotations

from pathlib import Path

from opensees_studio.core import Project, ProjectMeta
from opensees_studio.core.default_materials import default_materials
from opensees_studio.core.defaults import ensure_dead_load_case
from opensees_studio.core.warehouse import (
    CODE_PRESETS,
    WarehouseLoads,
    WarehouseSpec,
    force_from_kn,
    plan_warehouse,
    pressure_from_kpa,
)
from opensees_studio.services import load_project, save_project

CODE = "rnc07"


def build_warehouse_project() -> Project:
    project = Project(ndm=3, ndf=6, meta=ProjectMeta(name="Gable warehouse 20 x 30 m"))
    units = project.meta.units
    project.materials.extend(default_materials(project.next_material_id(), units))
    ensure_dead_load_case(project)

    spec = WarehouseSpec(
        span=20.0,
        eave_height=6.0,
        frame_spacing=6.0,
        n_frames=6,
        slope=0.10,
        purlin_spacing=1.5,
        girt_spacing=1.5,
        rafter_fly_brace_every=2,
    )
    preset = CODE_PRESETS[CODE]
    loads = WarehouseLoads(
        code=CODE,
        roof_dead=pressure_from_kpa(0.10, units),
        roof_live=pressure_from_kpa(preset.roof_live_kpa, units),
        midspan_point=force_from_kn(preset.midspan_point_kn, units),
    )
    plan = plan_warehouse(project, spec, loads=loads)
    plan.apply(project)
    print(plan.warehouse.summary())
    return project


def main() -> None:
    project = build_warehouse_project()
    project.validate_references()
    print(
        f"Built '{project.meta.name}' — {len(project.nodes)} nodes, "
        f"{len(project.elements)} elements, {len(project.analyses)} cases, "
        f"{len(project.combinations)} combinations."
    )
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
