"""Shared command replay and the published reinforced-concrete section."""

from pathlib import Path

from opensees_studio import commands as cmd
from opensees_studio import core as c
from opensees_studio.services import save_project
from opensees_studio.viewmodels import ProjectViewModel


class Builder:
    """Each step uses the same undoable mutation as its desktop dialog.

    A documentation replay may supply a callback that presents the step's
    real dialog before its command is pushed. No model JSON is constructed.
    """

    def __init__(self, name, ndf=3, replay=None, vm=None):
        self.vm = vm or ProjectViewModel()
        self.vm.new_project(ndm=2, ndf=ndf)
        self.vm.project.meta.name = name
        self.vm.project.meta.units = c.UnitSystem.US_IN_KIP
        self.replay = replay

    def step(self, kind, value, command):
        if self.replay:
            self.replay(self.vm, kind, value)
        self.vm.undo_stack.push(command)

    def node(self, x, y):
        node = c.Node(id=len(self.vm.project.nodes) + 1, coords=(x, y, 0.0))
        self.step("node", node, cmd.AddNodesCommand(self.vm, [node]))
        return node.id

    def support(self, ids, ux=True, uy=True, rz=True):
        value = (ux, uy, False, False, False, rz if self.vm.project.ndf == 3 else False)
        self.step("support", (ids, value), cmd.SetRestraintCommand(self.vm, set(ids), value))

    def mass(self, nid, ux, uy, rz):
        value = (ux, uy, 0.0, 0.0, 0.0, rz)
        self.step("mass", (nid, value), cmd.SetMassCommand(self.vm, {nid}, value))

    def material(self, material):
        self.step("material", material, cmd.AddMaterialsCommand(self.vm, [material]))

    def section(self, section, template=None):
        self.step("section", (section, template), cmd.AddSectionsCommand(self.vm, [section]))

    def element(self, element):
        self.step("element", element, cmd.AddElementsCommand(self.vm, [element]))

    def equal(self, retained, constrained, dofs):
        value = c.EqualDOFConstraint(
            retained_node=retained, constrained_node=constrained, dofs=dofs
        )
        self.step("equal", value, cmd.AddEqualDOFConstraintCommand(self.vm, value))

    def pattern(self, pid, name, constant=False, series_id=None):
        sid = series_id or pid
        if not any(ts.id == sid for ts in self.vm.project.time_series):
            cls = c.ConstantTimeSeries if constant else c.LinearTimeSeries
            value = cls(id=sid, name=name)
            self.step("series", value, cmd.AddTimeSeriesCommand(self.vm, value))
        value = c.PlainLoadPattern(id=pid, name=name, time_series_id=sid)
        self.step("pattern", value, cmd.AddLoadPatternCommand(self.vm, value))

    def load(self, pid, ids, fx=0.0, fy=0.0, mz=0.0):
        value = (fx, fy, 0.0, 0.0, 0.0, mz)
        self.step(
            "load", (pid, ids, value), cmd.AddNodalLoadsCommand(self.vm, set(ids), value, pid)
        )

    def case(self, case):
        self.step("case", case, cmd.AddAnalysisCasesCommand(self.vm, [case]))

    def finish(self):
        self.vm.project.validate_references()
        return self.vm.project


def rc_section(builder):
    builder.material(
        c.Concrete01(id=1, name="Confined core", fpc=-6, epsc0=-0.004, fpcu=-5, epsU=-0.014)
    )
    builder.material(c.Concrete01(id=2, name="Cover", fpc=-5, epsc0=-0.002, fpcu=0, epsU=-0.006))
    builder.material(c.Steel01(id=3, name="Reinforcement", Fy=60, E0=30000, b=0.01))
    patches = [
        c.RectangularPatch(material_id=mid, n_fib_y=ny, n_fib_z=1, y_i=yi, z_i=zi, y_j=yj, z_j=zj)
        for mid, ny, yi, zi, yj, zj in [
            (1, 10, -10.5, -6, 10.5, 6),
            (2, 10, -12, 6, 12, 7.5),
            (2, 10, -12, -7.5, 12, -6),
            (2, 2, -12, -6, -10.5, 6),
            (2, 2, 10.5, -6, 12, 6),
        ]
    ]
    layers = [
        c.StraightLayer(
            material_id=3, n_bars=n, bar_area=0.6, y_start=y, z_start=6, y_end=y, z_end=-6
        )
        for n, y in [(3, 10.5), (2, 0), (3, -10.5)]
    ]
    builder.section(c.FiberSection(id=1, name="RC 15 x 24", patches=patches, layers=layers))


def rc_frame(builder):
    for x, y in [(0, 0), (360, 0), (0, 144), (360, 144)]:
        builder.node(x, y)
    builder.support([1, 2])
    rc_section(builder)
    builder.section(c.ElasticSection(id=2, name="Elastic beam", E=4030, A=360, Iz=8640))
    for eid, nodes in [(1, (1, 3)), (2, (2, 4))]:
        builder.element(
            c.ForceBeamColumn(
                id=eid, nodes=nodes, section_id=1, geom_transf="PDelta", integration_points=5
            )
        )
    builder.element(c.ElasticBeamColumn(id=3, nodes=(3, 4), section_id=2))
    builder.pattern(1, "Gravity")
    builder.load(1, [3, 4], fy=-180)
    builder.case(
        c.StaticCase(
            id=1,
            name="Gravity",
            pattern_ids=[1],
            n_steps=10,
            load_factor_increment=0.1,
            system="BandGeneral",
            constraints="Transformation",
            algorithm="Newton",
            tolerance=1e-12,
            max_iter=10,
        )
    )


def save_built(project, script):
    return save_project(project, Path(script).with_suffix(".osmodel"))
