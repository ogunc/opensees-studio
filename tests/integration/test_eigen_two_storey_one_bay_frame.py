"""Integration test for the two-storey one-bay frame eigen example."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import ModalCase  # noqa: E402
from opensees_studio.services import load_project, save_project  # noqa: E402
from opensees_studio.services.opensees_runner import OpenSeesRunner  # noqa: E402


def _reload(proj, tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "two_storey_one_bay.osmodel"
    save_project(proj, path)
    reloaded = load_project(path)
    reloaded.validate_references()
    return reloaded


def test_two_storey_one_bay_frame_modal_periods_and_shapes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from examples.eigen_two_storey_one_bay_frame import build_eigen_two_storey_one_bay_frame

    proj = _reload(build_eigen_two_storey_one_bay_frame(), tmp_path)
    modal = next(c for c in proj.analyses if isinstance(c, ModalCase))
    r = OpenSeesRunner(proj).run(modal)

    assert len(r.eigenvalues) == 2
    assert r.eigenvalues[0] > 0.0
    assert r.eigenvalues[1] > r.eigenvalues[0]

    periods = [2.0 * math.pi / math.sqrt(v) for v in r.eigenvalues]
    assert periods[0] == pytest.approx(0.6285, rel=0.02)
    assert periods[1] == pytest.approx(0.2359, rel=0.02)

    # Normalize by the roof translation on the left column line.
    phi1_story1 = r.mode_shapes[1][3][0]
    phi1_story2 = r.mode_shapes[1][5][0]
    phi2_story1 = r.mode_shapes[2][3][0]
    phi2_story2 = r.mode_shapes[2][5][0]

    ratio1 = phi1_story1 / phi1_story2
    ratio2 = phi2_story1 / phi2_story2

    assert ratio1 == pytest.approx(0.3869, rel=0.02)
    assert ratio2 == pytest.approx(-1.2923, rel=0.02)

    # Symmetric frame: paired left/right joints share the same Ux modal value.
    for mode in (1, 2):
        assert r.mode_shapes[mode][3][0] == pytest.approx(r.mode_shapes[mode][4][0], abs=1e-12)
        assert r.mode_shapes[mode][5][0] == pytest.approx(r.mode_shapes[mode][6][0], abs=1e-12)
