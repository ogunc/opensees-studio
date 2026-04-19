"""Tests for bbox_for_section — used to draw extruded sections in 3D."""

from __future__ import annotations

import math

import pytest

from opensees_studio.core import (
    CircularPatch,
    ElasticSection,
    FiberSection,
    Project,
    RectangularPatch,
    StraightLayer,
)
from opensees_studio.services.section_bbox import bbox_for_section


# ── ElasticSection ────────────────────────────────────────────────
def test_elastic_section_back_solves_rectangle() -> None:
    """An ElasticSection is treated as a rectangle: A = b·h and
    Iz = b·h³/12 determine (b, h) uniquely."""
    # Known rectangle: b = 0.3, h = 0.5 → A = 0.15, Iz = 3.125e-3
    b, h = 0.30, 0.50
    A = b * h
    Iz = b * h ** 3 / 12.0
    Iy = h * b ** 3 / 12.0
    sec = ElasticSection(
        id=1, name="R",
        E=200e9, A=A, Iz=Iz, Iy=Iy, G=80e9, J=1e-6,
    )
    dims = bbox_for_section(sec)
    assert dims is not None
    w_y, h_z = dims
    assert w_y == pytest.approx(b, rel=1e-9)
    assert h_z == pytest.approx(h, rel=1e-9)


# ── FiberSection ──────────────────────────────────────────────────
def test_fiber_section_bbox_from_rect_patch() -> None:
    sec = FiberSection(
        id=1,
        patches=[RectangularPatch(
            material_id=1, n_fib_y=4, n_fib_z=4,
            y_i=-0.15, z_i=-0.25, y_j=0.15, z_j=0.25,
        )],
    )
    dims = bbox_for_section(sec)
    assert dims is not None
    w_y, h_z = dims
    assert w_y == pytest.approx(0.30)
    assert h_z == pytest.approx(0.50)


def test_fiber_section_bbox_includes_circ_patches() -> None:
    sec = FiberSection(
        id=1,
        patches=[CircularPatch(
            material_id=1, n_fib_circ=8, n_fib_rad=2,
            y_center=0.0, z_center=0.0,
            r_outer=0.2,
        )],
    )
    dims = bbox_for_section(sec)
    assert dims is not None
    assert dims[0] == pytest.approx(0.40)
    assert dims[1] == pytest.approx(0.40)


def test_fiber_section_bbox_grows_for_layers() -> None:
    """A bar layer that extends past the patches must widen the bbox."""
    sec = FiberSection(
        id=1,
        patches=[RectangularPatch(
            material_id=1, n_fib_y=2, n_fib_z=2,
            y_i=-0.10, z_i=-0.10, y_j=0.10, z_j=0.10,
        )],
        layers=[StraightLayer(
            material_id=2, n_bars=3, bar_area=1e-4,
            y_start=-0.15, z_start=0.12,
            y_end=0.15, z_end=0.12,
        )],
    )
    dims = bbox_for_section(sec)
    assert dims is not None
    # y extents: layer [-0.15, 0.15] (wider than patch [-0.10, 0.10]) → 0.30
    # z extents: patch [-0.10, 0.10] + layer z=0.12 → [-0.10, 0.12] → 0.22
    assert dims[0] == pytest.approx(0.30)
    assert dims[1] == pytest.approx(0.22)


def test_empty_fiber_section_returns_none() -> None:
    sec = FiberSection(id=1)
    assert bbox_for_section(sec) is None
