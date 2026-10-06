"""Official example 03. Auto dense eigen solver replaces the script's ARPACK."""

from examples.official._common import Builder, c, save_built


def build_portal_frame_2d(replay=None, vm=None):
    b = Builder("Official 03: Seven-storey portal", replay=replay, vm=vm)
    heights = [162, 162, 156, 156, 156, 156, 156]
    y = 0
    for floor in range(8):
        for x in (0, 360, 720):
            b.node(x, y)
        if floor < 7:
            y += heights[floor]
    b.support([1, 2, 3])
    for mid in range(5, 24, 3):
        b.equal(mid, mid - 1, [1])
        b.equal(mid, mid + 1, [1])
        b.mass(mid, 0.49, 1e-10, 1e-10)
    properties = [
        (51.7, 2150),
        (62.1, 2670),
        (72.3, 3230),
        (84.4, 3910),
        (32.5, 3330),
        (38.3, 4020),
        (47.1, 5120),
    ]
    for sid, (area, inertia) in enumerate(properties, 1):
        b.section(c.ElasticSection(id=sid, name=f"Section {sid}", E=29500, A=area, Iz=inertia))
    eid = 1
    for column, sections in enumerate(
        ([3, 3, 3, 2, 2, 1, 1], [4, 4, 4, 3, 3, 2, 2], [3, 3, 3, 2, 2, 1, 1]), 1
    ):
        for floor, sid in enumerate(sections):
            ni = column + floor * 3
            b.element(c.ElasticBeamColumn(id=eid, nodes=(ni, ni + 3), section_id=sid))
            eid += 1
    for floor, sid in enumerate([7, 7, 6, 6, 5, 5, 5], 1):
        for bay in (1, 2):
            ni = floor * 3 + bay
            b.element(c.ElasticBeamColumn(id=eid, nodes=(ni, ni + 1), section_id=sid))
            eid += 1
    b.pattern(1, "Lateral loads")
    for nid, force in zip(range(4, 23, 3), [2.5, 5, 7.5, 10, 12.5, 15, 20], strict=True):
        b.load(1, [nid], fx=force)
    b.case(c.ModalCase(id=1, name="Seven modes", n_modes=7))
    b.case(c.StaticCase(id=2, name="Linear static", pattern_ids=[1]))
    return b.finish()


def main():
    save_built(build_portal_frame_2d(), __file__)


if __name__ == "__main__":
    main()
