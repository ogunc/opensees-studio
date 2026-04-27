"""OpenSees Example 4. Portal Frame: inelastic uniaxial-section build."""

from __future__ import annotations

from pathlib import Path
import sys

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from opensees_studio.services import load_project, save_project  # noqa: E402

if __package__:
    from ._ex4_portal2d_common import (  # noqa: E402
        ANALYSIS_DT,
        ANALYSIS_STEPS,
        INELASTIC_SECTION_VARIANT,
        PUSH_STEP,
        PUSH_TARGET,
        REFERENCE_PUSH_TCL,
        REFERENCE_SINE_TCL,
        build_ex4_portal2d_inelastic_section,
    )
else:
    from _ex4_portal2d_common import (  # noqa: E402
        ANALYSIS_DT,
        ANALYSIS_STEPS,
        INELASTIC_SECTION_VARIANT,
        PUSH_STEP,
        PUSH_TARGET,
        REFERENCE_PUSH_TCL,
        REFERENCE_SINE_TCL,
        build_ex4_portal2d_inelastic_section,
    )


def main() -> None:
    project = build_ex4_portal2d_inelastic_section()
    project.validate_references()
    print(f"Built '{project.meta.name}'")
    print(f"  Build Tcl: {INELASTIC_SECTION_VARIANT.build_tcl_name}")
    print(f"  Analysis Tcls: {REFERENCE_PUSH_TCL.name}, {REFERENCE_SINE_TCL.name}")
    print(f"  Pushover target = {PUSH_TARGET}, step = {PUSH_STEP}")
    print(f"  Sine transient: dt = {ANALYSIS_DT}s, steps = {ANALYSIS_STEPS}")
    out_path = Path(__file__).with_suffix(".osmodel")
    save_project(project, out_path)
    print(f"Saved -> {out_path}")
    restored = load_project(out_path)
    restored.validate_references()
    assert restored.model_dump(by_alias=True) == project.model_dump(by_alias=True)
    print("Round-trip OK.")


if __name__ == "__main__":
    main()
