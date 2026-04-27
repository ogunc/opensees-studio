"""Integration tests for OpenSees Example 4 portal-frame variants."""

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
        ("build_ex4_portal2d_elastic_element", "examples.ex4_portal2d_elastic_element", False),
        ("build_ex4_portal2d_inelastic_section", "examples.ex4_portal2d_inelastic_section", True),
        ("build_ex4_portal2d_inelastic_fiber_section", "examples.ex4_portal2d_inelastic_fiber_section", True),
    ],
)
def test_ex4_variant_pushover_runs(tmp_path, builder_name: str, module_name: str, nonlinear: bool) -> None:  # type: ignore[no-untyped-def]
    mod = __import__(module_name, fromlist=[builder_name, "PUSH_STEP", "PUSH_TARGET"])
    proj = _reload(getattr(mod, builder_name)(), tmp_path, builder_name)
    push_case = next(c for c in proj.analyses if isinstance(c, PushoverCase))
    result = OpenSeesRunner(proj).run(push_case)

    expected_pts = int(mod.PUSH_TARGET / mod.PUSH_STEP) + 1
    if "fiber_section" in builder_name:
        assert len(result.control_disp) >= int(0.9 * expected_pts)
        assert result.control_disp[-1] >= 0.9 * mod.PUSH_TARGET
    else:
        assert len(result.control_disp) == expected_pts
        assert result.control_disp[-1] == pytest.approx(mod.PUSH_TARGET, abs=5e-3)
    assert max(result.base_shear) > 0.0

    early = (result.base_shear[5] - result.base_shear[0]) / (result.control_disp[5] - result.control_disp[0])
    late = (result.base_shear[-1] - result.base_shear[-6]) / (result.control_disp[-1] - result.control_disp[-6])
    if nonlinear:
        assert early > 1.25 * late
    else:
        assert early == pytest.approx(late, rel=0.03)


@pytest.mark.parametrize(
    ("builder_name", "module_name"),
    [
        ("build_ex4_portal2d_elastic_element", "examples.ex4_portal2d_elastic_element"),
        ("build_ex4_portal2d_inelastic_section", "examples.ex4_portal2d_inelastic_section"),
        ("build_ex4_portal2d_inelastic_fiber_section", "examples.ex4_portal2d_inelastic_fiber_section"),
    ],
)
def test_ex4_variant_sine_runs(tmp_path, builder_name: str, module_name: str) -> None:  # type: ignore[no-untyped-def]
    mod = __import__(module_name, fromlist=[builder_name, "ANALYSIS_DT", "ANALYSIS_STEPS"])
    proj = _reload(getattr(mod, builder_name)(), tmp_path, f"{builder_name}_sine")
    case = next(c for c in proj.analyses if isinstance(c, TransientCase))

    results_dir = Path(tempfile.mkdtemp(prefix=f"{builder_name}_"))
    result = OpenSeesRunner(proj).run(case, results_dir=results_dir)
    time = result.time()
    top_l = result.node_disp_history(3)
    top_r = result.node_disp_history(4)

    if "fiber_section" in builder_name:
        assert len(time) >= 30
        assert time[-1] >= 0.3
    else:
        assert len(time) == mod.ANALYSIS_STEPS
    assert result.dt == pytest.approx(mod.ANALYSIS_DT)
    assert top_l[:, 0].max() > 1e-3
    assert top_l[:, 0].min() < -1e-3
    assert abs(top_l[:, 0] - top_r[:, 0]).max() < 0.01
    assert max(abs(top_l[:, 1])) < 1.0
