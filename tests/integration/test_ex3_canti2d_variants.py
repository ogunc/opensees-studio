"""Integration tests for OpenSees Example 3 cantilever build variants."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import PushoverCase, TransientCase  # noqa: E402
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def _reload(proj, tmp_path, stem: str):  # type: ignore[no-untyped-def]
    path = tmp_path / f"{stem}.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


@pytest.mark.parametrize(
    ("builder_name", "module_name", "nonlinear"),
    [
        ("build_ex3_canti2d_elastic_element", "examples.ex3_canti2d_elastic_element", False),
        ("build_ex3_canti2d_inelastic_section", "examples.ex3_canti2d_inelastic_section", True),
        ("build_ex3_canti2d_inelastic_fiber_section", "examples.ex3_canti2d_inelastic_fiber_section", True),
    ],
)
def test_ex3_variant_pushover_runs(tmp_path, builder_name: str, module_name: str, nonlinear: bool) -> None:  # type: ignore[no-untyped-def]
    mod = __import__(module_name, fromlist=[builder_name, "PUSH_STEP", "PUSH_TARGET"])
    proj = _reload(getattr(mod, builder_name)(), tmp_path, builder_name)
    push_case = next(c for c in proj.analyses if isinstance(c, PushoverCase))
    result = OpenSeesRunner(proj).run(push_case)

    expected_pts = int(mod.PUSH_TARGET / mod.PUSH_STEP) + 1
    assert len(result.control_disp) == expected_pts
    assert result.control_disp[-1] == pytest.approx(mod.PUSH_TARGET, rel=1e-6)
    assert max(result.base_shear) > 0.0

    early = (result.base_shear[5] - result.base_shear[0]) / (result.control_disp[5] - result.control_disp[0])
    late = (result.base_shear[-1] - result.base_shear[-6]) / (result.control_disp[-1] - result.control_disp[-6])
    if nonlinear:
        assert early > 2.0 * late
    else:
        assert early == pytest.approx(late, rel=0.02)


@pytest.mark.parametrize(
    ("builder_name", "module_name"),
    [
        ("build_ex3_canti2d_elastic_element", "examples.ex3_canti2d_elastic_element"),
        ("build_ex3_canti2d_inelastic_section", "examples.ex3_canti2d_inelastic_section"),
        ("build_ex3_canti2d_inelastic_fiber_section", "examples.ex3_canti2d_inelastic_fiber_section"),
    ],
)
def test_ex3_variant_earthquake_runs(tmp_path, builder_name: str, module_name: str) -> None:  # type: ignore[no-untyped-def]
    mod = __import__(module_name, fromlist=[builder_name, "ANALYSIS_DT", "ANALYSIS_STEPS"])
    proj = _reload(getattr(mod, builder_name)(), tmp_path, f"{builder_name}_eq")
    eq_case = next(c for c in proj.analyses if isinstance(c, TransientCase))

    results_dir = Path(tempfile.mkdtemp(prefix=f"{builder_name}_"))
    result = OpenSeesRunner(proj).run(eq_case, results_dir=results_dir)
    time = result.time()
    top = result.node_disp_history(2)
    ux = top[:, 0]
    uy = top[:, 1]

    assert len(time) == mod.ANALYSIS_STEPS
    assert result.dt == pytest.approx(mod.ANALYSIS_DT)
    assert ux.max() > 1e-4
    assert ux.min() < -1e-4
    assert max(abs(uy)) < 1.0
