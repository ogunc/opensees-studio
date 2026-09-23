"""Unit tests for the Material Tester view model: protocols, derived values, errors.

No openseespy here.  Runs that need the real solver (Elastic linearity,
Steel02 loop) live in ``tests/integration/test_material_tester_vm.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from opensees_studio.core import ElasticIsotropic, ElasticUniaxial, HystereticSM, Project, Steel02
from opensees_studio.services.material_tester import MaterialTestResult, test_uniaxial_material
from opensees_studio.viewmodels.material_tester_vm import (
    MaterialTesterViewModel,
    cycle_energies,
    cyclic_protocol,
    derive_values,
    increasing_protocol,
    monotonic_protocol,
    strain_history,
)


def _project() -> Project:
    return Project(
        materials=[
            ElasticIsotropic(id=1, E=30e9, nu=0.2),
            ElasticUniaxial(id=2, E=200e9, name="elastic"),
            Steel02(id=3, Fy=420e6, E0=200e9, b=0.01),
            HystereticSM(id=4, pos_env=[(1.0, 0.01), (2.0, 0.02)]),
        ]
    )


def _mock_tester(mat, protocol):
    """Run the real service against a mocked ``ops`` module (no solver)."""
    return test_uniaxial_material(mat, protocol, ops_module=MagicMock())


# ---- protocol generators ---------------------------------------------------


def test_monotonic_history_length_and_peak() -> None:
    h = strain_history(monotonic_protocol(0.01, 20))
    assert len(h) == 20
    assert h[-1] == pytest.approx(-0.01)
    assert np.all(np.diff(h) < 0.0)


def test_cyclic_history_length_peaks_and_signs() -> None:
    n, cycles, a = 10, 3, 0.02
    h = strain_history(cyclic_protocol(a, cycles, n))
    assert len(h) == 3 * n * cycles
    assert h.min() == pytest.approx(-a)
    assert h.max() == pytest.approx(a)
    for k in range(cycles):
        cyc = h[3 * n * k : 3 * n * (k + 1)]
        assert cyc[n - 1] == pytest.approx(-a)  # compression peak first
        assert cyc[2 * n - 1] == pytest.approx(a)  # then tension peak
        assert cyc[-1] == pytest.approx(0.0)  # back to zero


def test_increasing_history_peaks_in_order() -> None:
    peaks, n = [0.001, 0.002, 0.004], 8
    h = strain_history(increasing_protocol(peaks, n))
    assert len(h) == 3 * n * len(peaks)
    for k, p in enumerate(peaks):
        cyc = h[3 * n * k : 3 * n * (k + 1)]
        assert cyc.min() == pytest.approx(-p)
        assert cyc.max() == pytest.approx(p)


@pytest.mark.parametrize("peaks", [[], [0.01, -0.02], [0.02, 0.01]])
def test_increasing_rejects_bad_peaks(peaks: list[float]) -> None:
    with pytest.raises(ValueError):
        increasing_protocol(peaks, 10)


# ---- derived values --------------------------------------------------------


def test_cycle_energy_of_elastic_perfectly_plastic_loop() -> None:
    """EPP, Fy=1, E=100 (eps_y=0.01), amplitude a=0.05, starting from the virgin state.

    0 -> -a: Fy^2/(2E) + Fy(a - eps_y) = 0.045; -a -> +a: 2 Fy(a - eps_y) = 0.08;
    +a -> 0: Fy(a - 2 eps_y) = 0.03.  Total 0.155.
    """
    n, a, fy, e = 2000, 0.05, 1.0, 100.0
    eps = strain_history(cyclic_protocol(a, 1, n))
    sig, s_prev, e_prev = [], 0.0, 0.0
    for x in eps:
        s_prev = float(np.clip(s_prev + e * (x - e_prev), -fy, fy))
        e_prev = x
        sig.append(s_prev)
    energies = cycle_energies(eps, np.asarray(sig), 3 * n)
    assert energies == pytest.approx([0.155], rel=1e-3)


def test_derive_values_linear() -> None:
    eps = np.linspace(-0.001, -0.01, 10)
    d = derive_values(eps, 200e9 * eps, None)
    assert d.peak_stress == pytest.approx(-2e9)
    assert d.secant_stiffness == pytest.approx(200e9)
    assert d.energy_per_cycle == []


# ---- view model ------------------------------------------------------------


def test_materials_list_only_testable_types_and_default_selection() -> None:
    vm = MaterialTesterViewModel(_project(), tester=_mock_tester)
    # nD ElasticIsotropic and the not-yet-supported HystereticSM are left out.
    assert [m.id for m in vm.materials()] == [2, 3]
    assert vm.material_id == 2
    assert vm.stress_unit() == "Pa"


def test_unlisted_material_cannot_be_run() -> None:
    vm = MaterialTesterViewModel(_project(), tester=_mock_tester)
    vm.material_id = 4  # HystereticSM: in the project, not in the list
    assert vm.run() is False
    assert vm.error == "No uniaxial material selected."


def test_service_type_error_yields_error_message() -> None:
    def _unsupported(mat, protocol):
        return test_uniaxial_material(
            HystereticSM(id=9, pos_env=[(1.0, 0.01), (2.0, 0.02)]), protocol, ops_module=MagicMock()
        )

    vm = MaterialTesterViewModel(_project(), tester=_unsupported)
    assert vm.run() is False
    assert vm.error is not None
    assert "TypeError: Unsupported material type: HystereticSM" in vm.error
    assert vm.strain.size == 0
    assert vm.result is None
    assert vm.summary_text() == vm.error


def test_invalid_parameters_yield_error_message() -> None:
    vm = MaterialTesterViewModel(_project(), tester=_mock_tester)
    vm.amplitude = 0.0
    assert vm.run() is False
    assert "amplitude must be positive" in (vm.error or "")


def test_divergence_yields_error_message() -> None:
    def diverging(mat, protocol):
        raise RuntimeError("Material tester failed to converge near strain=-0.01")

    vm = MaterialTesterViewModel(_project(), tester=diverging)
    assert vm.run() is False
    assert "failed to converge" in (vm.error or "")


def test_run_and_csv_with_fake_tester(tmp_path: Path) -> None:
    def fake(mat, protocol):
        eps = strain_history(protocol).tolist()
        return MaterialTestResult(
            strain=eps, stress=[mat.E * x for x in eps], material_name="e", protocol=protocol
        )

    vm = MaterialTesterViewModel(_project(), tester=fake)
    vm.protocol_kind = "increasing"
    vm.peaks = [0.001, 0.002]
    vm.steps_per_half_cycle = 5
    assert vm.run() is True
    assert vm.strain.size == 30
    assert vm.derived is not None
    assert vm.derived.energy_per_cycle == pytest.approx([0.0, 0.0], abs=1e-3)
    out = vm.export_csv(tmp_path / "t.csv")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# material: 2: Elastic (elastic)"
    assert lines[1].startswith("# protocol: Cyclic, increasing amplitude, peaks 0.001 0.002")
    assert lines[2] == "strain,stress [Pa]"
    assert len(lines) - 3 == 30
    assert "," in lines[3] and ";" not in lines[3]
