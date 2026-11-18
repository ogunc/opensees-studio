"""Release markers: colored dots on bars, with their own visibility."""

from __future__ import annotations

import numpy as np
from tools.render_bench import RecordingPlotter

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticSection,
    EndRelease,
    FrameReleases,
    Node,
    Project,
)
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer


def _project(releases: FrameReleases) -> Project:
    return Project(
        nodes=[
            Node(id=1, coords=(0.0, 0.0, 0.0)),
            Node(id=2, coords=(6.0, 0.0, 0.0)),
        ],
        sections=[
            ElasticSection(
                id=1,
                name="Rect",
                E=200e9,
                A=0.15,
                Iz=3.125e-3,
                Iy=1.125e-3,
                G=80e9,
                J=1e-6,
            )
        ],
        elements=[ElasticBeamColumn(id=1, nodes=(1, 2), section_id=1, releases=releases)],
    )


def _render(project: Project, settings: ViewSettings | None = None) -> RecordingPlotter:
    plotter = RecordingPlotter()
    ModelRenderer(plotter, settings=settings or ViewSettings()).render(project)
    return plotter


def test_releases_use_one_staggered_dot_per_action_and_colour() -> None:
    plotter = _render(
        _project(
            FrameReleases(
                i=EndRelease(released=("M2", "M3")),
                j=EndRelease(released=("T",)),
            )
        )
    )
    names = set(plotter.named)
    colors = ModelRenderer._RELEASE_COLORS
    assert f"releases_{colors['M2'].lstrip('#')}" in names
    assert f"releases_{colors['M3'].lstrip('#')}" in names
    assert f"releases_{colors['T'].lstrip('#')}" in names
    m3_points = plotter.named[f"releases_{colors['M3'].lstrip('#')}"][0].points
    m2_points = plotter.named[f"releases_{colors['M2'].lstrip('#')}"][0].points
    assert np.linalg.norm(np.asarray(m3_points) - np.asarray(m2_points)) > 0.0

    actor = plotter.named[f"releases_{colors['M3'].lstrip('#')}"][0]
    # Points, not a sphere glyph: a bar end costs one vertex.
    assert actor.n_points == 1


def test_partial_fixity_is_yellow() -> None:
    plotter = _render(_project(FrameReleases(i=EndRelease(released=("M3",), springs={"M3": 50.0}))))
    assert "releases_ffd60a" in plotter.named


def test_releases_can_be_hidden_without_hiding_frame_offsets() -> None:
    project = _project(FrameReleases(j=EndRelease(released=("M3",))))
    hidden = _render(project, ViewSettings(show_releases=False))
    assert not any(name.startswith("releases_") for name in hidden.named)

    shown = _render(project, ViewSettings(show_frame_assignments=False))
    assert any(name.startswith("releases_") for name in shown.named)
