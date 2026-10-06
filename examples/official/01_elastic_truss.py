"""Official example 01. Source tags are unchanged; no solver substitutions."""

from examples.official._common import Builder, c, save_built


def build_elastic_truss(replay=None, vm=None):
    b = Builder("Official 01: Elastic truss", 2, replay, vm)
    for xy in [(0, 0), (144, 0), (168, 0), (72, 96)]:
        b.node(*xy)
    b.support([1, 2, 3])
    b.material(c.ElasticUniaxial(id=1, name="Elastic", E=3000))
    for eid, area in [(1, 10), (2, 5), (3, 5)]:
        b.element(c.TrussElement(id=eid, nodes=(eid, 4), area=area, material_id=1))
    b.pattern(1, "Applied load")
    b.load(1, [4], fx=100, fy=-50)
    b.case(c.StaticCase(id=1, name="Linear static", pattern_ids=[1], system="BandSPD"))
    return b.finish()


def main():
    save_built(build_elastic_truss(), __file__)


if __name__ == "__main__":
    main()
