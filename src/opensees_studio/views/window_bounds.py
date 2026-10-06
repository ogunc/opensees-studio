"""Window frame bounds arithmetic, independent of the window system."""


def fitted_frame(
    client_size: tuple[int, int],
    frame: tuple[int, int, int, int],
    available: tuple[int, int, int, int],
    fraction: float = 1.0,
    *,
    center: bool = False,
) -> tuple[int, int, int, int]:
    """Return frame x/y and client width/height, allowing for decoration margins."""
    x, y, fw, fh = frame
    ax, ay, aw, ah = available
    cw, ch = client_size
    extra_w, extra_h = fw - cw, fh - ch
    width = min(cw, max(1, int(aw * fraction) - extra_w))
    height = min(ch, max(1, int(ah * fraction) - extra_h))
    fw, fh = width + extra_w, height + extra_h
    if center:
        x, y = ax + (aw - fw) // 2, ay + (ah - fh) // 2
    else:
        x = min(max(x, ax), ax + aw - fw)
        y = min(max(y, ay), ay + ah - fh)
    return x, y, width, height
