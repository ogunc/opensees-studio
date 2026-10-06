"""Decorated frame arithmetic without Qt or a window manager."""

import pytest

from opensees_studio.views.window_bounds import fitted_frame


@pytest.mark.parametrize("origin", [(0, 0), (-1280, -900), (1920, 80)])
@pytest.mark.parametrize("center,fraction", [(False, 1.0), (True, 0.9)])
def test_decorated_frame_fits_available_area(origin, center, fraction):
    ax, ay = origin
    area = (ax, ay, 1280, 900)
    # The failing X11 geometry: a 1280 x 900 client with 2 x 25 decoration.
    frame = (ax - 1, ay - 20, 1282, 925)
    x, y, width, height = fitted_frame((1280, 900), frame, area, fraction, center=center)
    assert ax <= x and ay <= y
    assert x + width + 2 <= ax + 1280
    assert y + height + 25 <= ay + 900
    assert width + 2 <= int(1280 * fraction)
    assert height + 25 <= int(900 * fraction)


def test_inside_frame_keeps_position_and_size():
    assert fitted_frame((600, 400), (100, 70, 616, 439), (0, 0, 1280, 900)) == (
        100,
        70,
        600,
        400,
    )
