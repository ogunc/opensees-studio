"""Screen-relative marker sizes: camera conversion and node point cloud."""

from __future__ import annotations

import numpy as np
import pytest
from tools.render_bench import RecordingPlotter

from opensees_studio.core import Node, Project
from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.canvas3d.model_renderer import ModelRenderer


class _Camera:
    def __init__(self, *, parallel: bool = True, scale: float = 5.0) -> None:
        self.parallel = parallel
        self.scale = scale
        self.position = (0.0, 0.0, 10.0)
        self.focal = (0.0, 0.0, 0.0)
        self.view_angle = 60.0

    def GetParallelProjection(self) -> int:
        return int(self.parallel)

    def GetParallelScale(self) -> float:
        return self.scale

    def GetPosition(self) -> tuple[float, float, float]:
        return self.position

    def GetFocalPoint(self) -> tuple[float, float, float]:
        return self.focal

    def GetViewAngle(self) -> float:
        return self.view_angle


class _Plotter(RecordingPlotter):
    def __init__(self, camera: _Camera | None = None) -> None:
        super().__init__()
        self.window_size = (800, 600)
        self.camera = camera or _Camera()
        self.mesh_kwargs: list[dict[str, object]] = []

    def add_mesh(self, mesh=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.mesh_kwargs.append(dict(kwargs))
        return super().add_mesh(mesh, *args, **kwargs)


def _project(*, mass: bool = False) -> Project:
    return Project(
        nodes=[
            Node(
                id=1,
                coords=(0.0, 0.0, 0.0),
                mass=(1.0, 1.0, 1.0, 0.0, 0.0, 0.0) if mass else (0.0,) * 6,
            )
        ]
    )


def test_parallel_projection_converts_screen_percent_to_world() -> None:
    plotter = _Plotter()
    renderer = ModelRenderer(plotter, settings=ViewSettings(node_size_percent=0.8))
    # 2 * parallel_scale / height = 2 * 5 / 600 world units per pixel.
    assert renderer._world_per_pixel() == pytest.approx(2.0 * 5.0 / 600.0)
    assert renderer._screen_size(2.0) == pytest.approx(0.02 * 600.0 * (2.0 * 5.0 / 600.0))
    assert renderer._screen_node_point_size() == pytest.approx(0.8 / 100.0 * 600.0)


def test_perspective_projection_uses_the_focal_distance() -> None:
    camera = _Camera(parallel=False)
    plotter = _Plotter(camera)
    renderer = ModelRenderer(plotter, settings=ViewSettings())
    expected = 2.0 * 10.0 * np.tan(np.radians(30.0)) / 600.0
    assert renderer._world_per_pixel() == pytest.approx(expected)
    assert renderer._screen_size(4.0) == pytest.approx(0.04 * 600.0 * expected)


def test_nodes_are_drawn_as_a_screen_space_point_cloud() -> None:
    plotter = _Plotter()
    settings = ViewSettings(node_size_percent=1.0)
    renderer = ModelRenderer(plotter, settings=settings)
    renderer.render(_project())

    assert renderer._node_pd is not None
    assert renderer._node_pd.n_points == 1
    point_kwargs = [kwargs for kwargs in plotter.mesh_kwargs if "point_size" in kwargs]
    assert point_kwargs
    assert point_kwargs[0]["point_size"] == pytest.approx(6.0)
    assert point_kwargs[0]["render_points_as_spheres"] is True


def test_mass_markers_are_screen_sized_and_only_added_when_visible() -> None:
    hidden = _Plotter()
    renderer = ModelRenderer(hidden, settings=ViewSettings())
    renderer.render(_project(mass=True))
    assert not renderer._screen_actors

    shown = _Plotter()
    renderer = ModelRenderer(shown, settings=ViewSettings(show_masses=True))
    renderer.render(_project(mass=True))
    assert renderer._screen_actors


def test_camera_settle_rebuilds_only_the_counted_overlays() -> None:
    plotter = _Plotter()
    renderer = ModelRenderer(plotter, settings=ViewSettings(show_masses=True))
    renderer.render(_project(mass=True))
    before = len(renderer._screen_actors)

    plotter.camera.scale = 10.0
    assert renderer.refresh_screen_sizes() is True
    assert len(renderer._screen_actors) == before
    assert renderer.refresh_screen_sizes() is False
    plotter.camera.scale = 10.1  # a 1 % change is below the rebuild threshold
    assert renderer.refresh_screen_sizes() is False
