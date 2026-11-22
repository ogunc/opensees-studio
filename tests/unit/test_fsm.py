"""core.design.fsm: the finite strip signature curve against closed-form buckling solutions."""

from __future__ import annotations

import math

import numpy as np
import pytest

from opensees_studio.core.design.aisi_buckling import (
    element_local_buckling,
    flat_widths,
    plate_buckling_stress,
)
from opensees_studio.core.design.fsm import (
    SignatureCurve,
    StripModel,
    axial_stress,
    bending_stress,
    buckling_factor,
    section_buckling,
    signature_curve,
    strip_model,
)
from opensees_studio.core.sections.cold_formed import ColdFormedShape, properties

E, NU = 29500.0, 0.3  # ksi
G = E / (2.0 * (1.0 + NU))


def _plate(width: float = 6.0, t: float = 0.1, n: int = 9) -> StripModel:
    nodes = np.column_stack([np.linspace(0.0, width, n), np.zeros(n)])
    strips = np.column_stack([np.arange(n - 1), np.arange(1, n)])
    return StripModel(nodes=nodes, strips=strips, t=t, E=E, nu=NU)


def _lipped_c() -> ColdFormedShape:
    return ColdFormedShape(profile="CS", d=9.0, bf=2.5, t=0.059, r=0.1875, lip=0.773)


def _unit_plate_stress(model: StripModel) -> float:
    width = float(np.ptp(model.nodes[:, 0]))
    return plate_buckling_stress(1.0, E, NU, model.t, width)


def test_a_plate_supported_on_both_edges_buckles_at_k_4() -> None:
    plate = _plate()
    last = len(plate.nodes) - 1
    held = [1, 4 * last + 1]  # out-of-plane displacement of both long edges
    factor, _ = buckling_factor(plate, axial_stress(plate), 6.0, fixed_dofs=held)
    assert factor / _unit_plate_stress(plate) == pytest.approx(4.0, rel=1e-3)


def test_a_plate_with_one_free_edge_follows_the_exact_coefficient() -> None:
    plate = _plate()
    # Simply supported loaded ends, one long edge supported, the other free:
    # k = 6 (1 - ν) / π² + (b / a)².
    factor, _ = buckling_factor(plate, axial_stress(plate), 18.0, fixed_dofs=[1])
    expected = 6.0 * (1.0 - NU) / math.pi**2 + (6.0 / 18.0) ** 2
    assert factor / _unit_plate_stress(plate) == pytest.approx(expected, rel=1e-2)


def test_a_plate_in_bending_buckles_at_k_23_9() -> None:
    plate = _plate()
    last = len(plate.nodes) - 1
    stress = 1.0 - 2.0 * np.linspace(0.0, 1.0, len(plate.nodes))
    held = [1, 4 * last + 1]
    lowest = min(
        buckling_factor(plate, stress, 6.0 * ratio, fixed_dofs=held)[0]
        for ratio in np.linspace(0.5, 0.9, 9)
    )
    assert lowest / _unit_plate_stress(plate) == pytest.approx(23.9, rel=5e-3)


@pytest.mark.parametrize("length", [200.0, 400.0])
def test_a_long_lipped_c_buckles_flexural_torsionally(length: float) -> None:
    shape = _lipped_c()
    p = properties(shape)
    model = strip_model(shape, E, NU)
    factor, _ = buckling_factor(model, axial_stress(model), length)
    sigma_ex = math.pi**2 * E / length**2 * p.Ix / p.A
    sigma_ey = math.pi**2 * E / length**2 * p.Iy / p.A
    sigma_t = (G * p.J + math.pi**2 * E * p.Cw / length**2) / (p.A * p.ro**2)
    beta = 1.0 - (p.x0 / p.ro) ** 2
    total = sigma_ex + sigma_t
    sigma_ft = (total - math.sqrt(total**2 - 4.0 * beta * sigma_ex * sigma_t)) / (2.0 * beta)
    assert factor == pytest.approx(min(sigma_ey, sigma_ft), rel=0.015)


@pytest.mark.parametrize("length", [200.0, 400.0])
def test_a_long_lipped_c_in_bending_buckles_laterally_torsionally(length: float) -> None:
    shape = _lipped_c()
    p = properties(shape)
    model = strip_model(shape, E, NU)
    factor, _ = buckling_factor(model, bending_stress(model, p), length)
    extreme = float(np.abs(model.nodes[:, 1] - p.yc).max())
    moment = factor * p.Ix / extreme
    sigma_ey = math.pi**2 * E / length**2 * p.Iy / p.A
    sigma_t = (G * p.J + math.pi**2 * E * p.Cw / length**2) / (p.A * p.ro**2)
    assert moment == pytest.approx(p.A * p.ro * math.sqrt(sigma_ey * sigma_t), rel=0.015)


def test_the_mesh_is_fine_enough() -> None:
    shape = _lipped_c()
    coarse = strip_model(shape, E, NU)
    fine = strip_model(shape, E, NU, strips_per_flat=12)
    a = buckling_factor(coarse, axial_stress(coarse), 6.7)[0]
    b = buckling_factor(fine, axial_stress(fine), 6.7)[0]
    assert a == pytest.approx(b, rel=2e-3)


def test_tension_everywhere_has_no_buckling_factor() -> None:
    plate = _plate()
    factor, mode = buckling_factor(plate, -axial_stress(plate), 6.0, fixed_dofs=[1])
    assert math.isinf(factor)
    assert not mode.any()


def test_the_minima_are_found_shortest_first_and_refined() -> None:
    lengths = np.geomspace(1.0, 100.0, 41)
    x = np.log(lengths)
    factors = (x - math.log(4.0)) ** 2 * (x - math.log(30.0)) ** 2 + 0.2 + 0.05 * x
    minima = SignatureCurve(lengths=lengths, factors=factors).minima()
    assert [round(length) for length, _ in minima] == [4, 30]


def test_a_lipped_c_has_a_local_minimum_above_the_element_model() -> None:
    shape = _lipped_c()
    buckling = section_buckling(shape, E, 50.0)
    local = buckling.compression.local
    assert local is not None
    assert buckling.compression.local_length == pytest.approx(6.7, rel=0.05)
    # The web restrained by the flanges buckles above a simply supported web.
    assert (
        element_local_buckling(shape, E, NU).pcr
        < local
        < 1.5 * element_local_buckling(shape, E, NU).pcr
    )
    assert buckling.compression.reference == pytest.approx(properties(shape).A * 50.0)


def test_a_smaller_lipped_c_shows_local_and_distortional_minima() -> None:
    shape = ColdFormedShape(profile="CS", d=6.0, bf=2.0, t=0.059, r=0.1875, lip=0.625)
    model = strip_model(shape, E, NU)
    minima = signature_curve(model, axial_stress(model)).minima()
    assert len(minima) == 2
    (local_length, local), (dist_length, dist) = minima
    assert local_length < dist_length
    assert local < dist


def test_strong_axis_bending_has_local_and_distortional_minima() -> None:
    buckling = section_buckling(_lipped_c(), E, 50.0).bending_x
    assert buckling.local is not None
    assert buckling.distortional is not None
    assert buckling.local < buckling.distortional
    assert buckling.local_length is not None
    assert buckling.distortional_length is not None
    assert buckling.local_length < buckling.distortional_length


def test_flat_widths_stop_at_the_bends() -> None:
    shape = _lipped_c()
    lip, flange, web, *_ = flat_widths(shape)
    assert web == pytest.approx(9.0 - 2.0 * (0.1875 + 0.059))
    assert lip == pytest.approx(0.773 - (0.1875 + 0.059))
    assert flange == pytest.approx(2.5 - 2.0 * (0.1875 + 0.059))
