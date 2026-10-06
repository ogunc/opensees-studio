"""Official example 02. Hardening with the original 1000 LoadControl steps."""

from examples.official._common import Builder, c, save_built


def build_nonlinear_truss(replay=None, vm=None):
    b = Builder("Official 02: Nonlinear truss", 2, replay, vm)
    for xy in [(0, 0), (72, 0), (168, 0), (48, 144)]:
        b.node(*xy)
    b.support([1, 2, 3])
    b.material(
        c.Hardening(id=1, name="Hardening", E=29000, sigmaY=36, H_iso=0, H_kin=0.05 / 0.95 * 29000)
    )
    for eid in range(1, 4):
        b.element(c.TrussElement(id=eid, nodes=(eid, 4), area=4, material_id=1))
    b.pattern(1, "Horizontal load")
    b.load(1, [4], fx=160)
    b.case(
        c.StaticCase(
            id=1,
            name="Load history",
            pattern_ids=[1],
            n_steps=1000,
            load_factor_increment=0.001,
            system="ProfileSPD",
            numberer="Plain",
            algorithm="Newton",
            test="NormUnbalance",
            tolerance=1e-8,
            max_iter=10,
        )
    )
    return b.finish()


def main():
    save_built(build_nonlinear_truss(), __file__)


if __name__ == "__main__":
    main()
