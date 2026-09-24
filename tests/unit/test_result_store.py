"""Result transport round trip: every result kind rebuilds exactly from disk."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from opensees_studio.services.result_store import (
    load_manifest,
    load_results,
    write_manifest,
    write_results,
)
from opensees_studio.services.results import (
    ModalResults,
    PushoverResults,
    ResponseSpectrumResults,
    StaticResults,
    TransientResults,
)
from opensees_studio.services.spectrum import ModeContribution

RNG = np.random.default_rng(7)


def _arr(*shape: int) -> np.ndarray:
    return RNG.standard_normal(shape) * 1e3 + 1e-9


def _same(a: dict[int, np.ndarray], b: dict[int, np.ndarray]) -> None:
    assert list(a) == list(b)
    for key in a:
        assert np.array_equal(a[key], b[key])


def test_static_round_trip(tmp_path: Path) -> None:
    src = StaticResults(
        case_id=4,
        case_name="Gravity",
        n_steps=3,
        node_disp={1: _arr(3, 3), 7: _arr(3, 3)},
        node_reaction={1: _arr(3, 3), 7: _arr(3, 3)},
        element_forces={2: _arr(3, 6)},
    )
    entry = write_results(src, tmp_path)
    back = load_results(entry, tmp_path)
    assert isinstance(back, StaticResults)
    assert (back.case_id, back.case_name, back.n_steps) == (4, "Gravity", 3)
    _same(src.node_disp, back.node_disp)
    _same(src.node_reaction, back.node_reaction)
    _same(src.element_forces, back.element_forces)
    assert entry["files"] == ["case_4.results.h5"]
    assert entry["completed_steps"] == 3


def test_pushover_round_trip(tmp_path: Path) -> None:
    src = PushoverResults(
        case_id=2,
        case_name="Push",
        n_steps=5,
        control_node=3,
        control_dof=1,
        control_disp=_arr(6),
        base_shear=_arr(6),
        node_disp={3: _arr(6, 3)},
        element_forces={1: _arr(6, 6), 9: _arr(6, 6)},
    )
    entry = write_results(src, tmp_path)
    back = load_results(entry, tmp_path)
    assert isinstance(back, PushoverResults)
    assert (back.n_steps, back.control_node, back.control_dof) == (5, 3, 1)
    assert np.array_equal(src.control_disp, back.control_disp)
    assert np.array_equal(src.base_shear, back.base_shear)
    _same(src.node_disp, back.node_disp)
    _same(src.element_forces, back.element_forces)


def test_modal_round_trip(tmp_path: Path) -> None:
    src = ModalResults(
        case_id=5,
        case_name="Modes",
        eigenvalues=np.array([12.5, 400.25, 9000.125]),
        mode_shapes={m: {1: _arr(6), 2: _arr(6)} for m in (1, 2, 3)},
    )
    entry = write_results(src, tmp_path)
    back = load_results(entry, tmp_path)
    assert isinstance(back, ModalResults)
    assert np.array_equal(src.eigenvalues, back.eigenvalues)
    assert list(back.mode_shapes) == [1, 2, 3]  # 1-indexed, order kept
    for m in (1, 2, 3):
        _same(src.mode_shapes[m], back.mode_shapes[m])


def test_response_spectrum_round_trip(tmp_path: Path) -> None:
    modes = [
        ModeContribution(
            mode_number=i,
            period=0.5 / i,
            frequency=2.0 * i,
            angular_frequency=4.0 * np.pi * i,
            participation_factor=1.25 / i,
            effective_mass=100.0 / i,
            mass_ratio=0.6 / i,
            sa_at_period=0.8 + 0.01 * i,
            modal_peak_disp={1: _arr(3), 2: _arr(3)},
        )
        for i in (1, 2)
    ]
    src = ResponseSpectrumResults(
        case_id=6,
        case_name="RS",
        direction=1,
        combination="CQC",
        combined_disp={1: _arr(3), 2: _arr(3)},
        modes=modes,
    )
    entry = write_results(src, tmp_path)
    back = load_results(entry, tmp_path)
    assert isinstance(back, ResponseSpectrumResults)
    assert (back.direction, back.combination) == (1, "CQC")
    _same(src.combined_disp, back.combined_disp)
    assert len(back.modes) == 2
    for a, b in zip(src.modes, back.modes, strict=True):
        for name in (
            "mode_number",
            "period",
            "frequency",
            "angular_frequency",
            "participation_factor",
            "effective_mass",
            "mass_ratio",
            "sa_at_period",
        ):
            assert getattr(a, name) == getattr(b, name)
        _same(a.modal_peak_disp, b.modal_peak_disp)


def test_transient_entry_points_at_the_runner_file(tmp_path: Path) -> None:
    h5 = tmp_path / "case_3.h5"
    h5.write_bytes(b"")
    src = TransientResults(
        case_id=3, case_name="EQ", h5_path=h5, n_steps=192, dt=0.01, n_steps_requested=400
    )
    entry = write_results(src, tmp_path)
    assert entry["files"] == ["case_3.h5"]
    assert entry["early_stop"] is True
    assert entry["warnings"] == ["Transient run stopped early: 192 of 400 steps, stopped early."]
    back = load_results(entry, tmp_path)
    assert isinstance(back, TransientResults)
    assert back.h5_path == h5
    assert (back.n_steps, back.dt, back.n_steps_requested) == (192, 0.01, 400)
    assert back.early_stop


def test_manifest_round_trip(tmp_path: Path) -> None:
    entries = [
        write_results(
            StaticResults(case_id=1, case_name="A", n_steps=1, node_disp={1: _arr(1, 3)}),
            tmp_path,
        )
    ]
    path = write_manifest(tmp_path, entries, "proj.run-snapshot.osmodel")
    assert path.name == "manifest.json"
    manifest = load_manifest(tmp_path)
    assert manifest["schema"] == 1
    assert manifest["project"] == "proj.run-snapshot.osmodel"
    assert [c["case_id"] for c in manifest["cases"]] == [1]
    assert manifest["cases"][0]["result_type"] == "StaticResults"
