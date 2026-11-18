"""Plane truss geometry: web patterns, chords, supports, and what is refused."""

from __future__ import annotations

import pytest

from opensees_studio.core import TrussError, TrussSpec, TrussType, build_truss


def _spec(**changes) -> TrussSpec:  # type: ignore[no-untyped-def]
    values = dict(span=12.0, depth=2.0, n_panels=4, material_id=1, chord_area=0.01, web_area=0.005)
    values.update(changes)
    return TrussSpec(**values)  # type: ignore[arg-type]


def _build(spec: TrussSpec, ndm: int = 2, ndf: int = 2):  # type: ignore[no-untyped-def]
    return build_truss(spec, ndm=ndm, ndf=ndf, first_node_id=10, first_element_id=100)


def _pairs(truss, ids) -> set[tuple[tuple[float, float], tuple[float, float]]]:  # type: ignore[no-untyped-def]
    # (span, height) of each node: a 2D truss stands in the X-Z plane (Z up).
    xy = {node.id: (node.coords[0], node.coords[2]) for node in truss.nodes}
    members = {e.id: e for e in truss.elements}
    return {tuple(sorted((xy[members[i].nodes[0]], xy[members[i].nodes[1]]))) for i in ids}  # type: ignore[misc]


def test_a_pratt_truss() -> None:
    truss = _build(_spec(plane="XZ"))
    assert len(truss.nodes) == 10  # 5 bottom + 5 top
    assert len(truss.chord_element_ids) == 8
    assert len(truss.web_element_ids) == 5 + 4  # verticals + diagonals
    web = _pairs(truss, truss.web_element_ids)
    # Diagonals run down towards mid-span.
    assert ((0.0, 2.0), (3.0, 0.0)) in web
    assert ((9.0, 0.0), (12.0, 2.0)) in web
    assert [e.id for e in truss.elements] == list(range(100, 117))


def test_a_howe_truss_mirrors_the_diagonals() -> None:
    web = _pairs(t := _build(_spec(truss_type=TrussType.HOWE, plane="XZ")), t.web_element_ids)
    assert ((0.0, 0.0), (3.0, 2.0)) in web
    assert ((9.0, 2.0), (12.0, 0.0)) in web


def test_a_warren_truss_has_top_nodes_at_mid_panel_and_no_verticals() -> None:
    truss = _build(_spec(truss_type=TrussType.WARREN, plane="XZ"))
    tops = sorted(n.coords[0] for n in truss.nodes if n.coords[2] > 0)
    assert tops == [1.5, 4.5, 7.5, 10.5]
    assert len(truss.web_element_ids) == 8
    web = _pairs(truss, truss.web_element_ids)
    assert all(a[0] != b[0] for a, b in web)  # no vertical member


def test_a_triangular_truss_closes_on_its_supports_without_repeating_a_chord() -> None:
    truss = _build(_spec(end_depth=0.0, plane="XZ"))
    assert len(truss.nodes) == 5 + 3  # the end top nodes are the supports
    pairs = [frozenset(e.nodes) for e in truss.elements]
    assert len(pairs) == len(set(pairs))
    assert all(len(p) == 2 for p in pairs)
    ridge = max(n.coords[2] for n in truss.nodes)
    assert ridge == 2.0


def test_supports_and_frame_model_restraints() -> None:
    truss = _build(_spec(plane="XZ"), ndm=3, ndf=6)
    first, last = truss.nodes[0], truss.nodes[4]
    assert first.restraint == (True, True, True, True, True, True)  # pin (+ out of plane)
    assert last.restraint == (False, True, True, True, True, True)  # roller on Z
    free = truss.nodes[2]
    assert free.restraint == (False, True, False, True, True, True)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"span": 0.0}, "span"),
        ({"n_panels": 1}, "two panels"),
        ({"end_depth": 3.0}, "between 0"),
        ({"end_depth": 1.0, "n_panels": 5}, "even number"),
        ({"end_depth": 1.0, "truss_type": TrussType.WARREN}, "odd number"),
        ({"web_area": 0.0}, "areas"),
    ],
)
def test_what_is_refused(changes, message) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TrussError, match=message):
        _spec(**changes)


def test_a_2d_model_builds_in_xz_only() -> None:
    with pytest.raises(TrussError, match="XZ"):
        _build(_spec(plane="YZ"))


def test_the_xy_plane_is_not_a_truss_plane() -> None:
    # Z is up: a truss stands in an elevation, never in plan.
    with pytest.raises(ValueError):
        _spec(plane="XY")
