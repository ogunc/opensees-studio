"""Contextual help: what every command is for, what its parameters mean, and
the mechanics behind the analysis it starts.

F1 anywhere opens the help at whatever the user is looking at. The content lives
here, in one place, grouped the way the menu bar is; the window that shows it is
:mod:`opensees_studio.views.help_window`, and the mapping from a menu action to
its topic is :data:`ACTION_TOPICS` (keyed by the action's attribute name on the
main window, so a new action without help fails a test rather than opening
nothing).

Writing help is prose, so the bodies are written in a tiny markup instead of
HTML: paragraphs separated by blank lines, ``-`` for bullets, ``#`` for a
heading, and ``**bold**``. :func:`body_to_html` turns that into what
``QTextBrowser`` renders, which keeps this file readable and reviewable.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from opensees_studio.core.help_glossary import GLOSSARY_GROUP, glossary_pages

#: Topic shown when nothing more specific is known.
DEFAULT_TOPIC = "index"

#: Qt property an action or a dialog carries to name its help topic.
TOPIC_PROPERTY = "helpTopic"


@dataclass(frozen=True)
class HelpTopic:
    """One page of help."""

    title: str
    group: str
    summary: str = ""
    body: str = ""
    see_also: tuple[str, ...] = field(default=())

    def html(self, *, resolver: object | None = None) -> str:
        """The topic as HTML, with its cross-references as links."""
        parts = [f"<h2>{html.escape(self.title)}</h2>"]
        if self.summary:
            parts.append(f"<p><i>{html.escape(self.summary)}</i></p>")
        parts.append(body_to_html(self.body))
        if self.see_also:
            links = []
            for topic_id in self.see_also:
                target = TOPICS.get(topic_id)
                label = html.escape(target.title if target else topic_id)
                links.append(f'<a href="topic:{topic_id}">{label}</a>')
            parts.append("<h4>See also</h4><p>" + " · ".join(links) + "</p>")
        del resolver
        return "".join(parts)


def _t(
    title: str,
    group: str,
    summary: str = "",
    body: str = "",
    *see_also: str,
) -> HelpTopic:
    return HelpTopic(title=title, group=group, summary=summary, body=body, see_also=see_also)


#: Groups in the order they appear in the help window's contents tree.
GROUP_ORDER: tuple[str, ...] = (
    "Getting started",
    "File",
    "Edit and tools",
    "Define",
    "Assign — joints",
    "Assign — frame",
    "Assign — areas",
    "Assign — groups",
    "Analyze",
    "Display",
    "Design",
    "View",
    "Options",
    "Help",
    "Mechanics",
    "Annex — OpenSees commands",
)


def body_to_html(text: str) -> str:
    """The tiny markup used above, as HTML for a ``QTextBrowser``.

    Blank line separates paragraphs, ``- `` starts a bullet, ``# `` a heading,
    and ``**bold**`` is bold. Everything else is escaped text.
    """
    out: list[str] = []
    bullets: list[str] = []

    def flush_bullets() -> None:
        if bullets:
            out.append("<ul>" + "".join(f"<li>{item}</li>" for item in bullets) + "</ul>")
            bullets.clear()

    for block in text.strip().split("\n"):
        line = block.strip()
        if not line:
            flush_bullets()
            continue
        if line.startswith("- "):
            bullets.append(_inline(line[2:]))
            continue
        flush_bullets()
        if line.startswith("# "):
            out.append(f"<h3>{_inline(line[2:])}</h3>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    flush_bullets()
    return "".join(out)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def resolve_topic(
    *,
    highlighted: str | None = None,
    menu_first: str | None = None,
    widget_topics: tuple[str | None, ...] = (),
) -> str:
    """Which page F1 should show, from what the caller found on screen.

    In order: the item under the cursor in the open menu, the first entry of
    that menu (a menu is open but nothing is highlighted), then whatever dialog
    or window is on top. Unknown ids are ignored rather than shown blank.
    """
    for candidate in (highlighted, menu_first, *widget_topics):
        if candidate and candidate in TOPICS:
            return candidate
    return DEFAULT_TOPIC


def topic(topic_id: str) -> HelpTopic:
    """The topic, or the default one when the id is unknown."""
    return TOPICS.get(topic_id) or TOPICS[DEFAULT_TOPIC]


def topics_in_group(group: str) -> list[tuple[str, HelpTopic]]:
    """Every topic of a group, in the order they were written."""
    return [(key, value) for key, value in TOPICS.items() if value.group == group]


def groups_present() -> list[str]:
    """The groups that actually have topics, in display order."""
    present = {value.group for value in TOPICS.values()}
    return [group for group in GROUP_ORDER if group in present]


TOPICS: dict[str, HelpTopic] = {
    # ──────────────────────────── Getting started ────────────────────────────
    "index": _t(
        "OpenSees Studio — how to use it",
        "Getting started",
        "The workflow: define, assign, analyse, look at the results.",
        """
# The workflow
1. **Define** the model: grids and nodes, then members (draw tools, the portal
frame wizard, or File → Import for a DXF drawing), then materials and sections.
2. **Assign** the properties: restraints and masses on joints, sections,
materials, geometric transformations and beam integration rules on frame
elements, loads in a load pattern.
3. **Analyze**: Analyze → Check Model Stability finds mechanisms before
anything is solved; then create one or more cases (Analyze → Cases) and run them
(Analyze → Run). The solve happens in a separate process, so a crash in the
solver cannot take the interface with it.
4. **Display** the results: deformed shape, mode shapes, force diagrams, time
histories, hysteresis, pushover curves and response spectra.

# Axes
**Z is the elevation axis of every model.** A 3D model uses X, Y and Z; a 2D
model lives in the **X-Z plane** (every node at y = 0, Z up), so its joints move
in Ux and Uz and turn in Ry, and gravity acts along -Z in both. OpenSees itself
solves a 2D model in its own x-y plane; the application translates on the way
in and out, so you never see that plane. A 2D project saved by an earlier build
(X-Y plane, Y up) is turned into the X-Z plane when it is opened, loads and
supports included, and is saved that way.

# Where things are
- The **3D viewport** is the model; clicking selects, dragging orbits.
- Everything is a command on an undo stack: Ctrl+Z undoes one model edit.
- The **Properties** panel follows the selection; with several joints or elements
  selected it edits what they share in one step.
- Every dialog that takes numbers has a help page: **press F1** while the menu
or the dialog is open.
- The **Console** dock keeps a log of what the application did, including the
commands it emitted to OpenSees.

# What is not here
Nothing is unit-aware behind your back: see **Units and the solver**. Nothing is
solved until you ask: editing the model never starts an analysis.

# Finding your way
- **Where is each command?** — the menu map lists every menu entry with one line.
- **I know the OpenSees command, where is it?** — the annex lists every command of
the OpenSeesPy manual and where it lives (a form, automatic, or a custom block).
""",
        "start.menu_map",
        "annex.index",
        "concepts.units",
        "concepts.model",
    ),
    "start.menu_map": _t(
        "Menu map: where each command is",
        "Getting started",
        "Every menu and what its entries do, in one page.",
        """
# File
- New (3D frame, 2D frame, 2D truss), Open, Save, Save As, Quit.
- Import → DXF drawing, PORTICO model (.s3d), SAP2000 text (.s2k / .$2k). Export →
  OpenSees script (.py), IFC (.ifc), SAP2000 text (.s2k), Report (PDF or HTML).

# Edit
- Undo / Redo, Delete, Select All, Clear Selection.
- Move, Replicate, Mirror; Interactive Table Editing (Ctrl+T); Check Model for
Duplicates; Mesh.

# Select
- Invert, Previous; All Joints / Elements; By Element Type, Section, Material,
Load Pattern or Group; Supported Joints, Joints with Mass, Elements with Self
Weight; Joints of Selected Elements, Elements between Selected Joints.

# Draw
- Select, Draw Node, Draw Frame, Draw Truss.

# Define
- Geometry and building: Coordinate System/Grids, Grid Wizard, Add Node, Storeys, Groups,
Section Cuts, Mass Source, Seismic Loads (ELF), Create Shell from 4 Nodes,
Create Portal Frame, Create Truss.
- Properties: Material Library (40 materials, Material Tester to check one),
Friction Models, Ground Motions, Section Library (elastic, nonprismatic, fibre
with W and RC templates, aggregator, plate, LayeredShell, PlateFiber, AISC
shapes).
- Loads: Add Linear / Path / Function TimeSeries, Add Plain Load Pattern, Add
Uniform Excitation, Add Multi-Support Excitation, Load Combinations.
- Custom OpenSees Commands: Python blocks for anything without a form.

# Assign
- Joint: Restraints, Masses, Springs, EqualDOF, Diaphragm, Rigid Link, Remove
Constraints, Point Loads, Imposed Displacement, Zero-Length Section, Bearing,
Link (twoNodeLink, Triple Friction Pendulum).
- Frame: Section, Material, Geometric Transformation, Beam Integration,
Releases/Partial Fixity, End Offsets, Insertion Point, Property Modifiers,
Distributed, Trapezoidal and Point Loads, Plastic Hinge.
- Area: Surface Load on Shells, Floor Load to Frames.
- Assign to Group (Ctrl+Shift+G).

# Analyze
- Cases (static, modal, pushover, transient, response spectrum, with every solver
option OpenSees 3.8 runs), Check Model Stability, Run.

# Display
- Show Results Of, Deformed Shape, Animate Mode Shape, Force Diagram, Shell
Contours, Time-History Plot and Animation, Hysteresis, Pushover Curve, Response
Spectrum, Display Options, Back to Model View. The Results panel holds the
tables (storeys, section cuts) and exports them to CSV.

# View, Options, Help
- Zoom Extents, Isometric / Top / Front / Right, Parallel Projection, Extruded
Sections, Show Grids, Show Grid Labels, Grid Line View, Hide Selected, Isolate
Selected, Show All Objects; Set Display Units; Help Contents (F1), About.
- **Right-click** on the model view (without dragging: a right drag zooms): with
something selected, what can be assigned or edited on it (joint, frame or area
options, group, move, replicate, mirror, delete); with nothing selected, the
grid and view options.
""",
        "index",
        "annex.index",
    ),
    "concepts.model": _t(
        "The model: nodes, elements, sections, materials, patterns",
        "Getting started",
        "How the pieces fit, and which one a given property belongs to.",
        """
- **Node** — a point with coordinates, a restraint (which DOF are fixed), a
lumped mass and a name. Nodes are shared: two members meeting at a corner use
one node, which is why the duplicate checker exists.
- **Element** — what connects nodes. A frame member (`ElasticBeamColumn`,
`ForceBeamColumn`, `DispBeamColumn`, `BeamWithHinges`) points at a **section**;
a truss points at a **material** and an area; a zero-length element or a bearing
points at materials, one per DOF; a shell points at a **plate section**.
- **Section** — the geometry and stiffness of a cross-section (elastic
properties, or fibres). A section carries its own modulus for elastic sections.
- **Material** — a constitutive law (`Steel02`, `Concrete04`, `Elastic`, …) with
its parameters. Fibre sections point at materials; trusses and zero-length
elements too.
- **Load pattern** — a time series plus the loads applied with it (nodal forces
and moments, distributed element loads). The same pattern can be used by several
analysis cases.
- **Analysis case** — what to solve: static, modal, pushover, transient or
response spectrum, with the numberer, system and convergence options it needs.

A member with a missing section, or a load on a node that does not exist, is
refused when the case runs: the model is validated before anything is emitted.
""",
        "concepts.units",
        "mechanics.static",
    ),
    # ──────────────────────────── Mechanics ────────────────────────────
    "concepts.units": _t(
        "Units and the solver",
        "Mechanics",
        "OpenSees has no units; the application never converts behind your back.",
        """
Every number you type is in **your** unit system, consistently: if lengths are
metres, forces are newtons and stresses pascals; if lengths are millimetres,
forces are newtons and stresses megapascals. The solver adds and multiplies
numbers and never checks them, so the only thing that matters is that one system
is used throughout.

- The project records two things: the **model units** its values are typed in,
  and the **display units** results are shown in (Options → Set Display Units).
  Changing the display units converts the numbers on diagrams, tables and plots
  — it never rewrites the model, and never re-interprets what you typed.
- **g** is 9.80665 m/s² in SI, 9806.65 mm/s² in millimetres, 32.174 ft/s² in US
  customary — the app picks the one matching your system when a dialog needs it.
- When a value is converted (an imperial shape into an SI project, for instance)
  the dialog shows both the published and the converted value, and says so.

The classic mistake is mixing them: a mass in kg with a stiffness in N/mm gives
a period that is wrong by a factor of 1000. There is no unit checking to catch
it — only a sanity check on the period, which the modal case reports.
""",
        "concepts.model",
        "analyze.run",
    ),
    "mechanics.static": _t(
        "Static analysis: what the parameters do",
        "Mechanics",
        "Solving K·u = F, in steps, and what changes when it is not linear.",
        """
A static case solves the equilibrium of the model under the loads of its
patterns. In one step, with a linear model, that is a single solve; in several
steps it is a load ramp, which is what a non-linear model needs.

# Parameters
- **Number of steps** — how many increments the pattern's total load is divided
  into. One step is right for a linear model; a model with material or geometric
  non-linearity needs enough steps for the solver to follow the path (10 to 100
  is typical).
- **Patterns** — which load patterns take part. Several patterns are applied
  together, which is how a gravity preload plus a lateral load is built.
- **Numberer / system** — how the equations are ordered and solved. The default
  is fine; a sparse direct system with an RCM or AMD numberer is faster on large
  models.
- **Tolerances and algorithm** — only used by the non-linear algorithms
  (Newton, ModifiedNewton, KrylovNewton) and the convergence test.

# Mechanics
The solver assembles the stiffness matrix **K** and the load vector **F** and
solves for the displacements **u**. Element forces follow from the displacements,
not from the loads directly — which is why a redundant structure redistributes
its internal forces as members yield.

A gravity preload followed by `loadConst -time 0.0` (the *chained* workflow) keeps
the gravity state and starts the next pattern from a zero time, so the following
transient or pushover does not re-apply gravity.
""",
        "analyze.cases",
        "analyze.run",
        "mechanics.numberer_system",
    ),
    "mechanics.modal": _t(
        "Modal analysis: periods, mode shapes and the solver choice",
        "Mechanics",
        "Eigenvalues of K·φ = ω²·M·φ, and why the solver is chosen for you.",
        """
A modal case solves the generalised eigenvalue problem **K φ = ω² M φ**. What
comes out is, per mode, an eigenvalue ω² (and its period T = 2π/ω), a mode shape
and a participation factor.

# Parameters
- **Number of modes** — how many. One rule of thumb is enough modes to cover
  90 % of the mass in each direction; the results panel reports the
  participation, so it is visible rather than assumed.
- **Mass** — comes from the nodal masses (Assign → Joint → Masses) and from any
  element mass (a section's density, `rho`). A model with no mass has no modes.

# Mechanics
- The **period** is what a response spectrum needs: the pseudo-acceleration
  Sa(T) read at the mode's period is what scales the mode.
- Mode shapes are normalised to unit modal mass and their sign is arbitrary;
  the application normalises it deterministically (largest component positive)
  so two runs of the same model look the same.
- A **repeated eigenvalue** (a symmetric structure has pairs) returns any two
  orthogonal shapes of that subspace; because "any" depends on the starting
  vector, the application orthogonalises them before display or combination.
- The solver is chosen rather than guessed: a dense solver for small models
  (exact, no start vector, deterministic), ARPACK above a size threshold
  (faster). ARPACK keeps its random start vector, so only its first call in a
  process is reproducible — the application re-runs such a case in a fresh child
  process instead of risking a different answer.
""",
        "mechanics.response_spectrum",
        "analyze.cases",
    ),
    "mechanics.pushover": _t(
        "Pushover: displacement control and what it produces",
        "Mechanics",
        "Pushing the structure to a target displacement to see how it yields.",
        """
A pushover case applies the pattern's load while increasing a **control
displacement** at a chosen node and DOF, recording the base shear at every step.
It is monotonic: the point is the sequence in which members yield and where the
capacity curve softens, not the cycling.

# Parameters
- **Control node and DOF** — where the displacement is imposed, usually the roof
  in the lateral direction (in 3D: DOF 1 for X, 2 for Y, 3 for Z, 4-6 for
  rotations; in a 2D model: 1 for X, 2 for Z, 3 for the rotation Ry). A positive
  target on a 2D rotation turns about +Y, the global convention.
- **Target displacement** — how far the node is pushed. It comes from a design
  displacement, a code formula, or a fraction of the height.
- **Steps and increment** — the target divided into steps. Too few and the
  solver can jump past a limit point.
- **Algorithm and convergence test** — Newton-family iterations with a
  displacement or energy test; a pushover that fails to converge is reporting a
  real limit, not necessarily a bug.

# Mechanics
The base shear vs roof displacement curve is the structure's capacity. On it:
- the **initial slope** is the elastic stiffness;
- **yielding** of the first member shows as a kink;
- a **softening** branch means a mechanism is forming;
- the **overstrength** is how much more the structure carries than its first
  yield, and the **ductility** is the displacement at the target over the yield
  displacement. Both are read off the curve by hand or by a bilinear fit.
""",
        "mechanics.static",
        "display.pushover",
    ),
    "mechanics.transient": _t(
        "Transient analysis: time steps, damping and convergence",
        "Mechanics",
        "Integrating M·ü + C·u̇ + K·u = F(t) step by step.",
        """
A transient case integrates the equations of motion in time. The input is a
ground motion (or a time series), and the output is a history of any response
you asked the recorder for.

# Parameters
- **Time step (dt)** — must be small enough to follow the input and the modes
  that matter: a rule of thumb is dt ≤ T_min/10 for the highest mode carrying
  mass. The application checks the record's own step and says if they differ.
- **Number of steps** — usually the record length divided by dt.
- **Rayleigh damping** — C = α·M + β·K, given as a damping ratio ζ at two
  periods (or as α and β directly). For one target ratio at one period, β =
  2ζ/ω. The two periods must bracket the range that matters; damping applied to
  a range it was not fitted to is a common source of surprises.
- **Modal damping** — one ratio ζ for each of the first N modes (OpenSees
  `modalDamping`), as SAP2000 and ETABS damp a modal history: every mode up to N
  gets exactly ζ, whatever its period, so no pair of periods has to be chosen.
  The runner computes the N modes after the preload (dense solver at or below
  500 free DOF, ARPACK above) and adds the modal damping to any Rayleigh damping;
  N is capped at the number of free DOF. Modes above N get no modal damping.
  Checked against the logarithmic decrement of a damped single-DOF free
  vibration.
- **Algorithm** — Newmark (average acceleration is the default and is
  unconditionally stable for linear models) or HHT with its α parameter.
- **Integrator and convergence** — for a non-linear model, the same Newton
  family and tolerance settings as a static case, per step.

# Mechanics
- Mass-proportional damping (α) damps the low modes; stiffness-proportional
  (β) damps the high ones. Fitting ζ at two periods sets both.
- **Stiffness-proportional damping with `-doRayleigh`** on the elements makes
  the damping forces depend on the element's own velocity, which is what makes
  an imposed support motion propagate correctly.
- A run that stops early did not converge; the log records the step it reached
  and the results keep what was computed. That is a result, not a crash: a
  non-converged step usually means the model is too coarse, the step is too
  large, or the structure has become unstable.
""",
        "mechanics.static",
        "define.ground_motions",
        "display.time_history",
    ),
    "mechanics.spectra": _t(
        "Design spectra: user table, ASCE 7-16 and TBDY 2018",
        "Mechanics",
        "Where a response spectrum comes from, and how a case ends up using it.",
        """
Three kinds of spectrum meet in this application, and they are not the same
object:

- a **target spectrum** (Ground Motions → Target spectrum) is a *design*
  spectrum in g: the dialog plots it and the record-scaling reads it;
- a **case response spectrum** (``project.spectra``) is the tabulated curve a
  response-spectrum *analysis* reads, with Sa in the project's acceleration unit;
- a **record spectrum** is computed from one ground motion, to compare with the
  design curve.

# Defining one
- **User table** — a period/Sa file (period in s, Sa in g). It is copied point for
  point into the case spectrum: resampling a table somebody typed would change
  the numbers they meant.
- **ASCE 7-16** — from the mapped MCER ``Ss`` and ``S1`` and the site class, or
  from ``SDS`` and ``SD1`` directly, with ``TL`` from the maps (4 s to 16 s).
  The site coefficients come from Tables 11.4-1 and 11.4-2 and the design values
  from Eqs. (11.4-1) to (11.4-4): ``SDS = 2/3 Fa Ss``, ``SD1 = 2/3 Fv S1``.
  - **Site class F is a site-specific study** (§11.4.8), and so is class E beyond
    ``Ss = 0.75`` or ``S1 = 0.1``: the dialog says so and refuses to extrapolate
    a table the standard leaves blank. Use your own site spectrum instead.
  - Where class **D is assumed** because the soil is unknown, §11.4.3 forbids
    ``Fa`` below 1.2; the checkbox applies that floor.
- **TBDY 2018** — the same machinery with the Turkish site coefficients, ``TL``
  fixed at 6 s.

# Using one
"Use as case spectrum" turns the spectrum on screen into the tabulated curve a
case reads, sampling the code's own corner periods (T0, Ts, TL) so the plateau
and both decay branches survive, and converting g into the project's acceleration
unit. A response-spectrum *case* then points at it by id (Analyze → Cases), and
the modal combination (SRSS or CQC) does the rest.
""",
        "define.ground_motions",
        "mechanics.response_spectrum",
        "display.response_spectrum",
    ),
    "mechanics.response_spectrum": _t(
        "Response spectrum: modes, damping and combination",
        "Mechanics",
        "Combining modal maxima with SRSS or CQC.",
        """
A response spectrum case takes a design spectrum (a code spectrum such as
TBDY-2018, a user target spectrum, or one computed from a record) and the
structure's modes, and combines them into a design response.

# Parameters
- **Spectrum and direction** — the curve, its damping and the direction it acts
  in (horizontal X/Y, vertical Z). The application's default damping is 5 %.
- **Combination rule** — **SRSS** (root sum of squares) or **CQC** (complete
  quadratic combination). SRSS assumes the modes are far apart in period; CQC
  adds the cross terms with a correlation coefficient and is the safer default
  when modes are close, which is the usual case for a 3D building.
- **Scale** — the spectrum can be scaled, and a target-spectrum case reports the
  scale factors it needs per period range.
- **Modes** — every mode used must be orthogonalised and sign-normalised; the
  application does that before combining, so a repeated eigenvalue cannot
  produce a wrong combination.

# Mechanics
The peak response of mode *i* is Sa(T_i)·Γ_i·φ_i (Γ is the modal participation
factor). The total peak is **not** the sum: the modes do not peak at the same
instant, so they are combined statistically. SRSS/CQC give a design envelope,
not a time history — nothing here tells you when the peak happens.

**Forces and reactions.** Element forces, support reactions and shell
resultants come from the static response of the model to each mode's equivalent
load, M·φ_i·Γ_i·Sa(T_i), combined component by component with the same rule and
correlation as the displacements. They are peak magnitudes (the sign is lost in
the combination), and a combination uses them as plus and minus that peak. The
load uses the nodal mass, as the participation factors do; mass given as an
element density is not in it.

For a nonlinear structure a response spectrum is only an approximation: it comes
from linear modal analysis. The usual route is a pushover or a transient.
""",
        "mechanics.modal",
        "display.response_spectrum",
    ),
    "mechanics.ground_motions": _t(
        "Ground motions: records, scaling and metadata",
        "Mechanics",
        "What the record library stores, and what scaling does to it.",
        """
Ground-motion records live in the project catalog (Define → Ground Motions).
Each entry has a file, a format, a unit and metadata computed from the samples.

# Parameters
- **Format** — PEER `.AT2`, two-column (time, acceleration) or single-column
  (acceleration only, with a step you provide).
- **Acceleration unit** — `g` or the project's acceleration unit; the factor is
  stored with the record so what the solver receives is explicit.
- **Scaling** — by PGA, by Sa(T1) of a chosen period, or to match a target
  spectrum over a period range. Every scaling factor is recorded in the case and
  reported, so a scaled run can be explained later.
- **Metadata** — PGA, PGV, PGD, Arias intensity and the 5-95 % significant
  duration, all computed from the samples and stored with the record.

# Mechanics
- A **uniform excitation** applies the record at every support, which is the
  usual assumption for a small structure; a **multiple-support** (imposed
  displacement) case drives chosen supports with different records, which is
  what a long bridge needs.
- The record's own time step and the analysis step must agree, or the
  application resamples and says so. Reading a 0.005 s record into a 0.01 s
  analysis silently halves the frequency content.
- Scaling by Sa(T1) is not the same as scaling by PGA: the first matches the
  demand at the structure's own period, the second matches the amplitude of the
  input.
""",
        "mechanics.transient",
        "define.ground_motions",
    ),
    "mechanics.isolators": _t(
        "Bearings and isolators: the bilinear model",
        "Mechanics",
        "Kinit, Qd, α1, α2 and μ — what each one does to the hysteresis loop.",
        """
An elastomeric or sliding bearing is modelled as a **zero-length element between
two coincident nodes**: the nodes sit at the same point, and the element's
deformation is the relative displacement between them.

# Parameters (elastomeric, plasticity or Bouc-Wen)
- **Kinit** — the initial (unloaded) shear stiffness. It sets the period at
  small amplitude.
- **Qd** — the characteristic strength: the height of the hysteresis loop's
  flat part. Divided by the weight it gives the isolator's `Qd/W`.
- **α1 / α2** — the post-yield stiffness ratio before and after the second
  branch; α2 < α1 is what produces the stiffening at large displacement.
- **μ, η, β, γ** — the Bouc-Wen parameters: the hysteresis shape. β and γ
  together set whether the loop is softening, hardening or bilinear.

# Parameters (friction pendulum, flat slider)
- **μ** — the friction coefficient. The force is μ·N, so the friction model
  matters: a constant Coulomb μ, a velocity-dependent μ(v), or a μ that depends
  on the normal force.
- **R_eff** — the pendulum radius: the restoring stiffness is W/R_eff and the
  isolated period is T = 2π·√(R_eff/g).

# Mechanics
A bilinear isolator's loop encloses an area 4·Qd·(D - Dy) per cycle: that area
is the energy the bearing dissipates, and it is the reason to use one. The
**effective damping** follows from that area; the **effective stiffness** from
the secant between the loop's extremes.
- The two nodes must be **coincident**; the duplicate checker leaves them alone
  on purpose (see Edit → Check Model for Duplicates).
- A bearing is not a support: if both nodes are free to translate the isolator
  does nothing. One of them is normally restrained.
""",
        "assign.bearing",
        "concepts.model",
    ),
    "mechanics.shells": _t(
        "Shells and plates: membrane, bending and thickness",
        "Mechanics",
        "Why a shell takes a plate section, and what the four nodes mean.",
        """
A `ShellMITC4` is a four-node shell: it carries in-plane membrane forces and
out-of-plane bending at once. Walls, slabs and shear walls are modelled with it.

# Parameters
- **The four nodes** — the element's own geometry. They must be listed around
  the face (counter-clockwise about its normal); Define → Create Shell from 4
  Nodes derives that order from the coordinates, because a scrambled list gives
  an inverted or twisted element.
- **The plate section** — `ElasticMembranePlateSection` carries E, ν, the
  thickness h and the density. OpenSees wants a *section* for a shell, not an
  nDMaterial: the thickness is the section's business, not the material's.
- **E and ν** — the membrane stiffness is E·h/(1-ν²) and the bending stiffness
  D = E·h³/(12(1-ν²)). Note the cube: halving the thickness makes the slab eight
  times more flexible in bending and leaves the membrane behaviour almost
  unchanged.

# Mechanics
- A mesh coarse in bending is **stiffer** than reality: it is a displacement
  formulation, so it approaches the exact answer from below. Refining converges
  (the application's test suite checks exactly this against the classical plate
  solution).
- The element has six DOF per node, including a drilling rotation that carries
  no stiffness of its own. Out-of-plane and drilling DOF have to be restrained
  where the structure is a genuine plate: the portal frame wizard does it for a
  plane frame, and a wall with free edges usually needs the drilling DOF tied.
- In a 3D model a plane frame is a mechanism unless its out-of-plane DOF are
  restrained; that is what the wizard's *restrain the out-of-plane degrees of
  freedom* option is for.
""",
        "define.create_shell",
        "define.section_library",
    ),
    "mechanics.fiber_sections": _t(
        "Fiber sections: patches, layers and yielding",
        "Mechanics",
        "Why a section made of fibres captures what an elastic one cannot.",
        """
A fibre section is a mesh of small areas, each tied to a uniaxial material. The
element integrates the material response over the section at every integration
point along the member, so:
- **axial force and bending interact** by construction (the neutral axis moves
  as the section yields), and
- **yielding, crushing and cracking are where they physically are** (the extreme
  fibre first), not a flag switched at the whole section.

# Parameters
- **Patches** — rectangular or circular regions of one material, divided into
  `n_fib_y × n_fib_z` fibres. More fibres is more accuracy and more cost; 8×8 to
  16×16 over a rectangular section is a working range.
- **Layers** — straight rows of reinforcement, each with an area, a material and
  a position (y, z).
- **Templates** in the fibre section editor: a W-shape, and two reinforced
  concrete ones. **RC rectangular**: the confined core inside the bar centrelines,
  four unconfined cover strips, top and bottom bars and optional side bars (depth
  h along local y, width b along z, cover to the bar centres). **RC circular**:
  a confined core disc, an unconfined cover ring and bars evenly around at the
  cover. Choose the confined concrete (e.g. `Concrete04` with Mander's confined
  strength), the cover concrete and the steel.
- **Materials** — the confinement of the core (`Concrete04` with the confined
  properties) and the steel (`Steel02` with `b` for the post-yield slope) decide
  the section's ductility. The section itself has no stiffness beyond them.

# Mechanics
- A fibre section is a **nonlinear** section: it needs a non-linear static,
  pushover or transient case, with enough steps and Newton iterations. A single
  linear step will not follow it.
- Moment-curvature is the section's response; the member's moment distribution
  comes from the integration rule along its length (Assign → Frame → Beam
  Integration), which must have enough points to sample the curvature.
- The app's Material Tester runs a single material through a strain protocol —
  useful to see a `Concrete04` or `Steel02` curve before trusting a section.
""",
        "define.material_library",
        "assign.integration",
        "define.material_tester",
    ),
    "mechanics.constraints": _t(
        "Constraints: equalDOF and imposed support motion",
        "Mechanics",
        "Tying degrees of freedom together, and driving supports with a record.",
        """
# equalDOF
`equalDOF` makes a node's chosen DOF follow another node's. Uses: a rigid floor
in a 3D model (tie every node of a level to a master node in the horizontal
DOF), a hinge modelled as two coincident nodes, or a rigid link between two
points. The DOF are given as numbers, 1-based, in the order the case uses them.

Two coincident nodes tied by `equalDOF` are a **deliberate** coincidence: Edit →
Check Model for Duplicates lists them and does not merge them.

# Imposed support motion
A multiple-support case drives chosen supports with a displacement record. The
nodes must be **restrained** in the driven DOF: in the static and modal cases
they behave as ordinary supports, and the runner swaps the fix for the imposed
motion when the pattern is emitted, so the ground is at rest until the transient
starts.

The velocity series is derived from the displacement by central differences
rather than left to OpenSees. That matters when elements use `-doRayleigh`:
the damping force depends on the element's velocity, and an imposed motion
without a matching velocity loses part of the input.
""",
        "assign.equal_dof",
        "assign.support",
        "assign.diaphragm",
    ),
    "mechanics.numberer_system": _t(
        "Numberer, system and solver",
        "Mechanics",
        "How the equations are ordered and solved, and when the choice matters.",
        """
These are per-case settings in Analyze → Cases. The defaults are sane; the
choice matters on large models and on models that struggle to converge.

- **Numberer** — the order the unknowns are put in. `Plain` is the model order;
  `RCM` (reverse Cuthill-McKee) and `AMD` (approximate minimum degree) reorder
  to reduce bandwidth and fill-in. On a model with thousands of DOF, AMD with a
  sparse system is often several times faster.
- **System** — how the linear system is stored and solved: `BandGeneral` and
  `ProfileSPD` for small banded problems, `SparseGeneral`/`UmfPack` for large
  sparse ones. `FullGeneral` is the reference implementation (slow, exact).
- **Algorithm** — `Linear` solves once (linear problems only); `Newton` and
  `ModifiedNewton` iterate for non-linear ones; `KrylovNewton` and
  `NewtonLineSearch` help when Newton stalls.
- **Convergence test** — an energy or residual test with a tolerance and a
  maximum number of iterations. Too tight wastes iterations; too loose accepts a
  wrong answer.
- **Eigen solver** — not a free choice: the application picks a dense solver for
  small models and ARPACK above the threshold (see Modal analysis), and
  re-executes an ARPACK case in a fresh process so the answer is reproducible.
""",
        "analyze.cases",
        "mechanics.static",
    ),
}

TOPICS.update(
    {
        # ──────────────────────────── File ────────────────────────────
        "file.new": _t(
            "File → New (3D Frame)",
            "File",
            "An empty three-dimensional model: ndm = 3, ndf = 6.",
            """
Creates a new project with six degrees of freedom per node (Ux, Uy, Uz, Rx, Ry,
Rz) and nothing in it. Use it for a space frame, a building with slabs, or
anything where the out-of-plane behaviour matters.

- The project is **dirty** and unsaved until you save it; closing or creating
  another one asks first if it is.
- A never-saved project writes a **pre-run snapshot** next to the app data when
  an analysis starts, so a crash does not lose the model.
- A grid is not created for you: Define → Coordinate System/Grids, or start from
  File → New 2D Frame, which brings the wizard and its grid.
""",
            "file.new_2d_frame",
            "define.grid",
        ),
        "file.new_2d_frame": _t(
            "File → New 2D Frame (and the portal frame wizard)",
            "File",
            "An empty 2D frame project, then the wizard that fills it, then its grid.",
            """
Creates a planar frame project (ndm = 2, ndf = 3: Ux, Uz, Ry per joint) and
immediately opens the **Portal Frame Wizard**. The frame is built on the XZ
plane (Z up), which is the only plane a 2D model has, and the wizard also writes the
**grid** it used, so you can keep drawing on the same lines. Cancelling the
wizard leaves the empty project.

# The wizard's values
- **Number of bays** and **bay width** — the columns sit at each bay line; the
total width is their product.
- **Eave height** — the height at which the roof starts, at the outer columns.
- **Roof** — one slope (mono-pitch), two slopes (gable) or flat; the **slope**
is a percentage. A gable rises to eave + slope × span/2 at the ridge; a
mono-pitch rises across the whole width.
- **Sections** — one for the columns, one for the rafters. If the project has
none, a default elastic section is created in the same undo step.
- **Column bases** — fixed (rotations restrained) or pinned (rotations free).
- **Plane and origin** — where the frame sits. Column tops follow the roof line,
so an interior column comes out as tall as the roof above it.
- **Restrain the out-of-plane DOF** — on for a frame analysed on its own (a
plane frame in a 3D model is a mechanism otherwise). Turn it off when you are
going to copy the frame and tie the copies together.

# Mechanics
Eave and ridge heights, the slope and the bay width are pure geometry: they
decide the member lengths, not the analysis. What changes the behaviour is the
**support condition** (a fixed base adds rotational restraint, which is what
makes a portal frame stiff) and the **sections** (bending stiffness).
""",
            "define.portal_frame",
            "file.new",
            "mechanics.static",
        ),
        "file.new_2d_truss": _t(
            "File → New 2D Truss",
            "File",
            "A planar truss: ndm = 2, ndf = 2, no rotational degrees of freedom.",
            """
Creates a project with two degrees of freedom per node (Ux, Uz: the model is in
the X-Z plane, Z up). Use it for a
genuine pin-jointed truss: with no rotational DOF there are no empty rows in the
stiffness matrix, so the solver does not have to be told what to do with a
rotational DOF that carries no stiffness.

- Members are `TrussElement` or `CorotTrussElement`, each with a material and an
  area. A member with no moment connection is what a truss is.
- Anything that needs bending (a beam, a frame) belongs in File → New 2D Frame.
- Applying a moment to a node of this model does nothing: there is no DOF for it.
""",
            "file.new_2d_frame",
            "concepts.model",
        ),
        "file.open": _t(
            "File → Open",
            "File",
            "Open a .osmodel project (and offer to recover a crashed run).",
            """
A project is a single JSON file with a schema version. Opening one that is newer
than the application is refused rather than quietly rewritten.

- If the current project has unsaved changes you are asked first.
- If an earlier run left a **pre-run snapshot** newer than the file, the
  application offers to restore it: that is the crash recovery path.
- The project you are leaving takes its own pre-run snapshot with it, so
  reopening it later does not offer a recovery nobody needs. Cancelling the
  prompt or the file dialog keeps both.
- An old `schema_version` is migrated on load and stamped with the current one
  on the next save.
- If File → Run Batch… solved this project and the model has not changed since,
  the application offers to **load the stored results**, so they can be viewed
  without running again.
""",
            "file.save",
            "file.save_as",
            "file.run_batch",
        ),
        "file.run_batch": _t(
            "File → Run Batch",
            "File",
            "Solve many project files unattended and keep each one's results.",
            """
Runs the analysis cases of many `.osmodel` files one after another (or a few at
a time) without opening them. Nothing in the project open in the window
changes; each file is read from disk as it was last saved.

- **Add Files… / Add Folder…** build the list. A folder adds every `.osmodel`
  directly inside it (not its subfolders); pre-run snapshots are left out.
- **Cases**: *All cases* runs every case of each project, in its own order.
  *Cases named* takes names or ids separated by commas (`Dead, Modal, 3`),
  ignoring upper and lower case; a project with none of them is *skipped*.
- **Parallel jobs**: how many projects solve at the same time. Each one is its
  own analysis process, so use at most one per processor core, fewer for big
  transient models (each holds its own model in memory).
- The table shows each file's status, the case running with its step, the time
  taken and, for a failure, the reason. **Cancel Batch** stops the running
  processes and drops the ones not started; the window cannot be closed while
  the batch runs.

The engine is the one chosen in Options → Solver, exactly as for Analyze → Run:
a case it does not run fails that file with the reason.

# Where the results go

Beside each project, `model.osmodel` keeps:

- `model_batch_results/`: the lossless result store (`case_<id>.results.h5`,
  `manifest.json`), `batch.json` (which model the results belong to) and
  `analysis.stderr.log` (the solver's own output);
- `model_results.sqlite`: the results database, one new run per case.

When the batch ends, `batch_summary.json` and `batch_summary.csv` (file,
status, time, cases, exit code, message) are written in the folder of the first
file.

Opening a solved project later (File → Open) offers to load the stored results
while the model is still the one they were computed on; after an edit to the
model they are not offered, since they would describe another model.

# From a terminal

`python -m opensees_studio.batch models/*.osmodel --cases all --jobs 4` does the
same without the window (`--engine` picks another engine, `--summary` another
summary name). A packaged build runs it as `OpenSeesStudio --batch …`.
""",
            "file.open",
            "analyze.run",
            "analyze.results_database",
        ),
        "file.save": _t(
            "File → Save",
            "File",
            "Write the project (and remove the pre-run snapshot).",
            """
Saves to the current path, or asks for one if the project has never been saved.
The file is written atomically: the previous version is replaced only once the
new one is complete, so a save cannot truncate the model you already have.

Saving clears the dirty flag and removes the pre-run snapshot, which only exists
to recover unsaved work.
""",
            "file.save_as",
            "file.open",
        ),
        "file.save_as": _t(
            "File → Save As",
            "File",
            "Write the project to a new path and continue from there.",
            """
Saves under a new name and makes that the current file. References that are
relative to the project (ground-motion records stored next to it) are rebased so
they keep pointing at the same files.
""",
            "file.save",
        ),
        "file.import_dxf": _t(
            "File → Import → DXF Drawing",
            "File",
            "Straight bars from a CAD drawing, as nodes and members.",
            """
Reads `LINE`, `LWPOLYLINE` and `POLYLINE` entities and turns them into
beam-column elements. Everything else in the drawing — circles, text, hatches,
blocks — is **counted and reported**: a drawing that imports four members where
you drew two hundred has to say so.

# The values the dialog asks for
- **Layers** — tick the ones that are structure. Construction lines and axes
  usually are not.
- **Units and scale** — the file's own `$INSUNITS` is turned into a factor to
  the project's unit and shown. A drawing with no units gets factor 1 and a note
  saying nothing was converted; set it by hand if the file lies.
- **Read the drawing as** — a plan (XY), a front elevation (XZ, the default:
  that is how frames are usually drawn), a side elevation (YZ), or `3D` to keep
  the file's own X, Y and Z.
- **Plane level** and **origin** — where the drawing plane sits and where the
  drawing's own (0, 0, 0) lands.
- **Merge tolerance** — endpoints closer than this become **one node**. Drawings
  repeat coordinates instead of sharing vertices; the default is one part per
  million of the drawing's size, and the number of merges is reported.
- **Member section** — the section every imported member gets (a default one is
  created if the project has none).

# What it does not do
- No supports and no loads: a drawing cannot say what is fixed or loaded. They
  arrive free; restrain them with Assign → Joint → Restraints.
- Curved polyline segments (bulges) are imported as straight chords, and the
  count is reported. Circles and arcs are not imported at all.
- The whole import is one undo step, and the imported nodes are left selected.
""",
            "define.portal_frame",
            "edit.check_duplicates",
        ),
        "file.import_s3d": _t(
            "File → Import → PORTICO Model (.s3d)",
            "File",
            "A model saved by PORTICO, as a new project scaled to the units you choose.",
            """
Reads a `.s3d` file from PORTICO (the browser-based structural analysis program,
`jpreyes/portico-core`) and makes it the **current project**. It replaces what is
open, so unsaved changes are asked about first, and the new project has no file
until you save it.

# Units
PORTICO never converts: the file's `units` label says which system its numbers
are in. **File units** is filled in from that label (`kN-m`, `kip-in`, `lb-in`,
…); change it if the label is wrong. **Project units** is the system the project
gets, and every value is **scaled** to it by its dimension: lengths, forces,
moments, stresses, masses, densities, spring stiffnesses and loads. A `kN-m`
file opened in `SI (m, N, kg, s, Pa)` has its forces multiplied by 1000 and its
densities in kg/m³. The **Scale** line shows the length and force factors.

Self weight is the material density times g in the project's units. PORTICO
always multiplies by 9.80665, which is only right for its own `kN-m`.

# What comes across
- Nodes, supports, support springs and nodal masses.
- Frame elements as elastic beam-columns. A section with shear areas makes a
  Timoshenko member, as in PORTICO, and the consistent mass matrix is used.
- Sections and materials: one elastic section per section, material and
  orientation used, with PORTICO's section modifiers applied to the values.
- End releases (torsion and bending) and end springs on released actions.
- Static load cases with their nodal, uniform and trapezoidal loads and self
  weight, each as a load pattern plus a linear static case of the same name.
- Prescribed support displacements, as one pattern every static case runs (as
  PORTICO imposes them in every static case).
- Load combinations and grid lines.
- **Areas** (quadrilaterals) as `ShellMITC4` with an elastic plate section per
  material and thickness; their element ids follow the members'. PORTICO's
  membrane and plate areas become full shells (a membrane gains bending, a plate
  gains membrane stiffness), which the log notes.
- **Diaphragms** as rigid diaphragms on PORTICO's master node (`masterId`, else
  the first node). The floor mass is spread equally over the floor's nodes on UX
  and UY (PORTICO uses the tributary of the beams).
- **Links**: a rigid link with all six DOFs is a rigid `beam` link, with the three
  translations a `bar`; a non-rigid link is an equalDOF of its DOFs.
- The **mass source**: its load cases and factors, the self weight when ticked,
  and the mass on all three translations, as PORTICO does.
- A model loaded only by prescribed displacements (a patch test) gets a static
  case of its own.
- **Cable** and **compression-only** members as trusses whose elastic material
  goes slack on the other side (`Eneg = 0` for a cable, a stiffness of 1e-9 E in
  tension for a strut). The static cases then run with Newton, and their
  combinations are no longer an exact superposition.

# Local axes
PORTICO gives a beam its local **y** up; OpenSees gives it local **z** up. Per
member the importer works out how the two triads relate and swaps `Iz`/`Iy`,
`Avy`/`Avz` and the bending releases where needed (the section name then ends in
"(axes 2-3)"). Distributed loads are re-projected onto the OpenSees axes, so they
keep their global direction.

# What it does not do (yet)
Counted in the summary and the log, never dropped silently: triangular areas
(there is no 3-node shell), areas of a 2D model, temperature loads, response
spectrum cases (the spectrum is not in the file), translational end releases,
unilateral, coupled and soil springs, a diaphragm's rotational mass and
accidental eccentricity, and distributed loads on a cable or a strut (a truss
takes none). A member with releases or a
trapezoidal load loses its shear deformation, because OpenSees' Timoshenko beam
takes neither.
""",
            "file.open",
            "file.import_dxf",
        ),
        "file.import_s2k": _t(
            "File → Import → SAP2000 Text (.s2k / .$2k)",
            "File",
            "A model saved as SAP2000 text tables, as a new project in the nearest unit system.",
            """
Reads a SAP2000 text file (`.s2k` or `.$2k`: tables of `Key=Value` records) and
makes it the **current project**. It replaces what is open, so unsaved changes
are asked about first, and the new project has no file until you save it.
SAP2000 is a trademark of Computers and Structures, Inc.; this reader was
written from the text format alone, without CSI software, and is not endorsed
by CSI.

# Units
The file's `CurrUnits` (for example `"KN, m, C"`) say what its numbers are in.
The project gets the nearest of the four systems (kN-m → m and N, kip-in → in
and kip, N-mm → mm and N, …) and every value is **scaled** to it by its
dimension. The log names both systems. A file without units is read as kN-m.

# What comes across
- **Joints** (global Cartesian, or with `GlobalX/Y/Z`) and their restraints.
  When only UX, UZ and RY are active and every joint is at Y = 0, the model
  becomes a **2D frame**.
- **Added joint masses** (`Mass1..3` and `MMI1..3`) and **support springs**
  (`U1..3`, `R1..3`), both in the joint local axes, which default to global. The
  mass source decides whether the added masses carry weight; a 2D model keeps
  only the in-plane components and reports the rest.
- **Grid lines** of the global system, with their labels.
- **Frames** as elastic beam-columns: the section and material assigned to each
  (a frame's own material overrides the section's), the local-axis angle, the
  mass (unit mass × area) and the weight (unit weight × area, read by a load
  pattern's self weight). Shear areas make a Timoshenko member, as SAP2000
  includes shear deformation.
- **Frame sections**: rectangular, I, pipe, box/tube and general by their
  property columns (the dimensions give closed-form values when those are
  missing), with the property modifiers applied to the values; other shapes by
  their properties only. Rectangles, I-shapes, pipes and tubes keep their shape
  for the extruded view. A **nonprismatic** section reads its segment table (in
  SAP2000's order, from the I end to the J end) into a `NonprismaticSection`
  template and subdivides each member into elastic pieces, 12 by default; the
  import asks for the piece count and the section can be edited later in Define >
  Section Library. A 2D model accepts a 0 in the inertia it does not bend about
  and in the torsion constant; a 3D section whose `J` is 0 gets a small one,
  because OpenSees needs torsional stiffness. Both substitutions are counted in
  the report.
- **End releases** of torsion and bending, partial-fixity springs, and each
  frame's **property modifiers** (`AMod`, `AS2Mod`, `AS3Mod`, `JMod`,
  `I22Mod`, `I33Mod`, `MassMod`, `WeightMod`, mapped to this program's local
  axes). A zero shear-area modifier turns shear deformation off; on a
  nonprismatic frame the segment sections' own shear areas govern, as in
  SAP2000's stored results.
- **Load patterns** with their self-weight multiplier, **joint forces** (global),
  **distributed frame loads** (uniform, trapezoidal or over part of the member,
  global, gravity, projected or local directions) and **point frame loads**.
- **Temperature loads** on frames: a uniform change, a joint-pattern variation
  along the member (its mean is used) and a cross-section gradient given per unit
  length, with the material's thermal expansion coefficient (`A1`).
- **Ground displacements** on restrained joints (support settlements), and
  **frame added mass** (`FRAME ADDED MASS ASSIGNMENTS`) added to the element's
  mass per length.
- **Rigid diaphragms** (`CONSTRAINT DEFINITIONS - DIAPHRAGM` and
  `JOINT CONSTRAINT ASSIGNMENTS`) as `RigidDiaphragm`, using SAP2000's
  floating centre-of-mass joint as the retained node so the runner can fix its
  out-of-plane DOFs. A diaphragm in a 2D model, a multi-level one, a joint
  outside its plane and a support left out of the floor are counted in the
  report.
- **Linear static load cases**, each with its load patterns. A pattern used with
  a factor other than 1 becomes a scaled copy (`LIVE x 0.5`). A file without
  load cases gets one per load pattern, as SAP2000 does. A case whose
  `InitialCond` names another imported static case runs it first as a preload.
- **Eigen modal cases**: a `LinModal` case with `ModeType=Eigen` becomes a modal
  case that asks for its `MaxNumModes`, with the solver left on this program's
  automatic routing (dense at or below 500 free DOF, ARPACK above). Other modal
  types, and a modal case with no `CASE - MODAL 1 - GENERAL` row, are counted in
  the report.
- **Response-spectrum cases**: a `LinRespSpec` case with a CQC or SRSS
  `ModalCombo` becomes a spectrum case on the file's first modal case, in its
  `U1..R3` direction and `ConstDamp`, with the tabulated function
  (`FUNCTION - RESPONSE SPECTRUM - USER`) as a project spectrum; `TransAccSF`
  takes its ordinates to the project units, and a `T = 0` point is read as
  `1e-6 s`. `ABS` and "10 Percent" combinations, more than one direction, a
  non-zero angle, accidental eccentricity and a second scale factor are counted
  in the report.
- **Combinations**: linear add, envelope, absolute add and SRSS, of cases and
  of other combinations.
- **Areas** with four joints and a shell section, as `ShellMITC4` with an
  elastic plate section. A Shell-Thin area becomes this thick-shell element,
  which also deforms in shear; the log notes it.

# Local axes
SAP2000 gives a frame's local 2 the upward direction in the member's vertical
plane (global +X for a vertical member), turned by its local-axis angle; OpenSees
gives a 3D beam its local z up. Per member the importer finds where local 2
lies and maps `I33`/`I22`, `AS2`/`AS3` and the M2/M3 releases onto this
program's axes (a section then used turned ends in "(axes 2-3)"). Loads are
re-projected, so they keep their direction.

# Damaged files
Every error names the table and the line it came from ("Frame 3 (CONNECTIVITY -
FRAME, line 57): joint 'C' is not defined."). A line inside a table that is not a
`Key=Value` record is counted in the summary instead of being skipped in silence,
and a file with no joints is refused rather than opened as an empty project. A
truncated or corrupted file always fails with a message; it never takes the
window down.

# Work in progress
This is not a complete SAP2000 reader. The full list of what is read, the known
approximations and the unsupported objects is in
`docs/sap2000-import-status.md` in the repository; the import log remains the
authoritative report for a particular file. Counted in the summary and the log,
never dropped silently:

- links, tendons, cables, solids and area types other than four-node shells;
- nonlinear/staged cases (`NonStatic`), buckling (`LinBuckling`), modal and
  direct history (`LinModHist`), steady state and moving loads;
- `ABS` and "10 Percent" spectrum combinations, a second direction/angle or
  accidental eccentricity on a spectrum case, and a non-static initial
  condition;
- frame end offsets, length offsets, insertion points, P-Delta/Corotational
  transformations, axial/shear releases and curved frames (imported straight);
- rigid links, equalDOF and body constraints; storeys, groups and section cuts;
  a 2D or multi-level diaphragm;
- gravity loads, moment loads on frames, some point-load directions, a
  temperature variation along the member (its mean is used), and ground
  displacements on free or spring-supported DOFs;
- range-add combinations and automatic lateral loads;
- a frame with releases or a non-uniform load keeps no shear deformation,
  because OpenSees' Timoshenko beam takes neither.
""",
            "file.export_s2k",
            "file.import_s3d",
            "file.open",
        ),
        "file.export_s2k": _t(
            "File → Export → SAP2000 Text",
            "File",
            "The frame model as SAP2000 text tables, readable again by Import.",
            """
Writes the project as a SAP2000 text file (`.s2k`) in the project's own units
(`CurrUnits`). Everything File → Import → SAP2000 Text reads is written, so an
exported file imports back to the same model. SAP2000 is a trademark of
Computers and Structures, Inc.; the file follows the text format and has not
been checked by CSI or in SAP2000.

# What is written
- Joints, restraints, added joint masses and support springs, global grid lines
  and the active DOFs (UX, UZ, RY only for a 2D frame).
- Elastic beam-columns on elastic sections, with their end releases,
  partial-fixity springs and per-frame property modifiers. Each section is
  written with SAP2000's local 2 on this program's local z (local y in 2D), and
  a member whose axes differ from
  SAP2000's default gets the local-axis angle that makes them match. A section
  with a shape (rectangle, I, pipe, tube) is written as that shape, any other as
  a general section; every one carries its area, inertias, torsion constant and
  shear areas (0 when the member has no shear deformation).
- One material per distinct set of modulus, shear modulus, unit weight and unit
  mass (named MAT1, MAT2, …).
- Shells (`ShellMITC4` on an elastic plate section) as thick-shell areas.
- Rigid diaphragms (`CONSTRAINT DEFINITIONS - DIAPHRAGM` and
  `JOINT CONSTRAINT ASSIGNMENTS`).
- Plain load patterns with their self weight, joint forces, and uniform,
  trapezoidal and point frame loads in local directions.
- Linear static cases, eigen modal cases, response-spectrum cases (CQC or SRSS)
  with their tabulated spectra, and combinations of static cases and of each
  other.

# What is not written
The export reports what it leaves out: other element and section types, end
offsets, insertion points, the mass source, shell and floor loads, imposed
displacements, temperature loads, nonlinear static, modal, spectrum and
transient cases, and constraints other than diaphragms (rigid links and
equalDOFs). A nonprismatic section
is written as the elastic pieces it was subdivided into, not as a SAP2000
`NONPRISMATIC` table, so the exported file carries the same mechanical model but
not the taper template.
""",
            "file.import_s2k",
            "file.export_ifc",
        ),
        "display.influence_line": _t(
            "Display → Influence Line",
            "Display",
            "Any response of an influence-line case against the load's position, and a vehicle on it.",
            """
An **influence-line case** (Analyze → Cases… → Add → *InfluenceLine*) walks a
load along a chain of frame members — a bridge girder, a crane runway — and
solves the model once per stop. Each stop's result holds every displacement,
reaction and member end force with the load there.

# Defining the case
- **Path**: the member ids in the order the load travels. Consecutive members
  must share a joint; each is walked from the joint it shares with the previous
  one, so a path can turn corners.
- **Stops per member**: equal intervals of every member (a joint shared by two
  members is one stop). Ten is plenty for straight members.
- **Load direction** and **value**: -1 along Z, the default, is a unit load
  downward. The analysis is linear elastic.
- **Vehicle axles** (optional): `load@offset` pairs, the offset measured behind
  the front axle, for example `35@0, 145@4.3, 145@8.6`. They prefill the dialog.

# The dialog
Pick the **response**: a joint displacement or a reaction (by joint and DOF) or a
member end force (by member, component and end, in the sign of the force
diagrams). The plot is its value **per unit load** in the sense of the case's
load, against the distance along the path.

**Envelope** moves the vehicle across the path in **both directions**, axle by
axle (an axle off the path counts nothing), and reports the largest and the
smallest effect and where the front axle stood. Axle loads are in the sense of
the case's load: with the default case a downward axle is positive.
""",
            "analyze.cases",
            "display.force_diagram",
        ),
        "design.steel_check": _t(
            "Design → Steel Frame Check (AISC 360-16)",
            "Design",
            "Demand/capacity ratios of steel members over the results of this session.",
            """
Checks every frame member whose section is an AISC shape of a covered family
against ANSI/AISC 360-16, by LRFD or ASD: **W, M, S, HP** (I-shapes), **C, MC**
(channels), **WT, MT, ST** (tees), **L with equal legs**, **rectangular and
square HSS**, **round HSS** and **pipes**. The section's **name** says which shape it is
(sections from Define → Section Library are named that way); type another shape
in the overrides to check a member with it.

# What is checked
- **Tension** D2-1 (yielding of the gross section). Rupture needs the net area
  and is left to you.
- **Compression** E3 flexural buckling about both axes, E4 torsional buckling,
  and the E7 effective area when the flange or the web is slender.
- **Major-axis flexure** F2 yielding and lateral-torsional buckling (with Lp, Lr
  and Cb), F3 flange local buckling. A noncompact web is noted, not checked (F4).
- **Minor-axis flexure** F6, **shear** G2.1 along the web and G6 along the flanges.
- **Interaction** H1-1a / H1-1b of the axial force and both moments.

The other families use their own sections of the Specification:
- **Channels**: E4 flexural-torsional buckling about the axis of symmetry, F2
  with c from F2-8b, F6, G2.1(b) and G6 with the full flange width.
- **Tees**: E4 flexural-torsional buckling, the stem as an unstiffened element
  (E7), F9 yielding, lateral-torsional buckling, flange and stem local buckling.
  The sign of the moment is not tracked, so the strength is the smaller of the
  stem in tension and the stem in compression.
- **Equal-leg angles**: E3 about the minor principal axis z, E4, F10 about the
  geometric axes without lateral-torsional restraint (0.8 My, toe in
  compression), G3. Unequal-leg angles are not designed (their flexure is about
  the principal axes).
- **Rectangular HSS**: E7 walls, F7 flange and web local buckling (the effective
  section modulus of F7-3 for a slender flange) and lateral-torsional buckling
  of a deep tube, G4. **Round HSS and pipes**: E7-6, F8, G5 with Lv half the
  member length.

HSS walls use the design thickness 0.93 tnom. The default Fy is 50 ksi: set it
for the material (A500 Grade C round HSS 46 ksi, A53 pipe 35 ksi). Torsion is
not checked.

The clear web height is taken as `d - 2 tf` (the table has no `k`), which is
slightly conservative.

# Where the demands come from
The dialog uses the results of the cases already **run in this session**; it runs
nothing. Tick the load sets to envelope (by default every combination, or every
static case when there is none). A combination is expanded into sums of cases:
Linear Add adds its terms, Envelope keeps each term, and a response spectrum
case enters as plus and minus its peak. Absolute Add and SRSS combinations have
no signed demands and are skipped with a note.

Each member is read at 25 stations along its length, span loads included. The
largest axial force, moments and shears are taken together (conservative for the
interaction), and Cb comes from the major-axis moment diagram (F1-1) unless you
set it. **Set Cb = 1.0 for a cantilever**: F1-1 assumes both ends braced.

# The values the dialog asks for
- **Method** LRFD (φ) or ASD (Ω); **Fy** (50 ksi by default, in the project's
  stress unit); **ratio limit** above which a member is reported **NG**.
- **Overrides for the selected members**: the AISC shape, K about each axis, the
  unbraced length of the compression flange Lb (0 = the member length) and Cb
  (0 = from the diagram). The buckling lengths are the member length times K.

Results: one row per member with its governing ratio, the check and equation
that govern and the load set that produced them; **Select failing members**
closes the dialog with them selected, and **Show ratios on the model** closes it
and paints every member by its ratio (Design → Display Steel Ratios on Model).
The settings are saved with the project, and File → Export → Report prints the
check when they are.
""",
            "design.steel_ratios",
            "design.drift_check",
            "define.load_combinations",
        ),
        "design.steel_ratios": _t(
            "Design → Display Steel Ratios on Model",
            "Design",
            "Paint every frame member by its governing AISC 360-16 ratio.",
            """
Runs the steel frame check with the settings saved in the project (or the
defaults: LRFD, 50 ksi, every combination) over the results of this session, and
draws each member in the colour of its governing demand/capacity ratio, with the
ratio written at mid-length:

- blue up to 0.5, teal up to 0.7, green up to 0.9 and orange up to the ratio limit
  (the steps are those fractions of the limit, so a limit of 0.95 keeps the reading);
- **red above the limit**;
- grey for a member the check does not cover (no AISC shape, or a section name
  that is not one).

The panel on the right shows the legend, the summary and the notes (load sets
skipped because a case has no result yet). **Select failing members** selects
the red ones; **Back to model** (or Display → Back to Model) removes the colours.

Nothing is stored: change the settings in Design → Steel Frame Check, then display
the ratios again.
""",
            "design.steel_check",
            "file.export_report",
        ),
        "design.drift_check": _t(
            "Design → Storey Drift Check",
            "Design",
            "Amplified inter-storey drift ratios against an allowable ratio.",
            """
For every static and response spectrum case with a result in this session, the
drift ratio of each storey (the difference of the floor displacements over the
storey height, see Define → Storeys) is multiplied by the **amplification** and
compared with the **allowable drift ratio**. A ratio above 1 is over the limit.

The **Code** list fills in common limits: ASCE 7-22 Table 12.12-1 (0.020, 0.015 or
0.010 h by risk category; set the amplification to Cd / Ie, since the analysis
gives elastic drifts), NCh433 (0.002 h at the centre of mass) and Eurocode 8.
Response spectrum drifts are combined per storey by the case's own rule, never
taken as the difference of two peak displacements.

The project needs storeys; the limit and the amplification are saved with it.
""",
            "design.steel_check",
            "define.storeys",
        ),
        "file.export_report": _t(
            "File → Export → Report (HTML / PDF)",
            "File",
            "A calculation report: the model, loads, cases and the results of this session.",
            """
Writes one document that reads top to bottom like a calculation report. Choose
**PDF** (A4, printed by Qt, no browser needed) or an **HTML page** (opens in any
browser and pastes into Word).

# Contents
- **Project** — name, description, author, date, units, model type and program
  version.
- **Model** — joints, supports, elements by type, materials, sections, patterns,
  cases, combinations, storeys, groups and section cuts, counted.
- **Materials** and **Sections** — every one with its values.
- **Load patterns** — the loads each holds and the sum of its joint loads.
- **Analysis cases** and **Load combinations** — with their patterns and terms.
- **Results** — one section per case run in this session *on the model as it is
  now*: peak displacements (and where), support reactions with their sum, the
  pushover curve, the periods, the storey table and the section cuts. Values
  are in the display units, with the Results panel's signs.
- **Steel frame check** — when the project has design settings (saved by
  Design → Steel Frame Check): the method, Fy, ratio limit and load sets, every
  checked member with its governing ratio, check, equation and load set, and the
  amplified storey drifts against the limit. Its values are in the project's units.

# Notes
- Results computed before the last model change are left out; run the cases again
  first. Nothing is run by the report itself.
- Long tables stop at 60 rows; the Results panel exports any table in full (CSV).
- Values below a billionth of a table's largest one print as 0 (solver
  round-off).
""",
            "file.export_ifc",
            "display.select_results",
        ),
        "file.export_ifc": _t(
            "File → Export → IFC",
            "File",
            "The model as IFC4: the physical BIM model and the structural analysis model.",
            """
Writes an IFC4 file (`.ifc`) with two linked descriptions of the structure, the
way BIM tools and structural programs exchange a model.

# The physical model (what BIM viewers draw)
- One building storey per storey (Define → Storeys) plus the base, each element
  in the storey it starts on.
- Frame members as **IfcColumn** (within 10° of vertical), **IfcBeam** (within
  10° of horizontal) or **IfcMember** (braces and every truss bar), extruded along
  their axis from their profile: an I or channel for an AISC section (looked up by
  its name), a rectangle, hollow or solid circle or angle from the section's
  shape, else the rectangle of the section's extent. Each carries a material
  profile set named after its section.
- Shells as **IfcSlab** (horizontal), **IfcWall** (vertical) or **IfcPlate**,
  their thickness extruded along the normal.

# The analytical model (what structural software reads)
- An IfcStructuralAnalysisModel (in-plane for a 2D model) with a point
  connection per node, its supports as boundary conditions, a curve member per
  frame or truss (end releases on the member's connection) and a surface member
  per shell with its thickness.
- One load case per Plain pattern, its action type guessed from the name (DEAD,
  LIVE, WIND, EQ …): nodal forces, uniform and trapezoidal member loads (a floor
  load as the member loads it becomes), point loads on members, shell pressures,
  imposed displacements, and the self weight as the case's self-weight
  coefficients. Load combinations become load groups of type combination with
  each case assigned by its factor.
- Every analytical member is assigned to its physical element.

# Good to know
- Coordinates and values stay in the project's units (metre, millimetre, foot or
  inch; newton or kip), declared in the file.
- Elements IFC has no member for (bearings, zero-length elements, plane quads)
  are left out, and so is a node no frame, truss or shell touches (a diaphragm's
  retained node) with its loads. The export says what it left out.
- Masses, analysis cases and results are not part of the file.
""",
            "file.export_script",
            "file.save",
        ),
        "file.export_script": _t(
            "File → Export → OpenSees script",
            "File",
            "The model as a plain OpenSeesPy script, optionally with one case.",
            """
Writes a `.py` script that rebuilds the model with `openseespy` calls, and
optionally runs one analysis case with its setup and step protocol.

The script is generated by running the real runner against a recorder, so it is
the **same command sequence the solver receives** — not a second implementation
that can drift from it. The exported script is checked against the application's
own results in the test suite.

Use it to keep a model, hand it to someone without the GUI, or move it into
another OpenSees workflow.
""",
            "analyze.run",
            "concepts.model",
        ),
        "file.quit": _t(
            "File → Quit",
            "File",
            "Close the application, asking about unsaved changes first.",
            """
Closes the window. If the project has unsaved changes you are asked whether to
save, discard or cancel. Closing the window from the window manager asks the
same question; a programmatic close (for instance while shutting down) does not.
""",
            "file.save",
        ),
    }
)

TOPICS.update(
    {
        # ──────────────────────────── Edit and tools ────────────────────────────
        "edit.undo": _t(
            "Edit → Undo",
            "Edit and tools",
            "Take back the last model edit (Ctrl+Z).",
            """
Every change to the model is a command on one undo stack: adding a node, moving a
selection, assigning a section, importing a drawing, fixing duplicates. Undo
takes the last one back; Redo puts it back.

- A command that touches several things — a wizard's frame plus its grid, an
import plus the section it needed — is **one** entry: one undo takes the whole
thing.
- The undo stack is not saved with the project: closing and reopening starts a
  new history.
- The stack is what makes a destructive experiment cheap: run it, look, undo.
""",
            "edit.redo",
            "edit.delete",
        ),
        "edit.redo": _t(
            "Edit → Redo",
            "Edit and tools",
            "Put back the edit Undo took away (Ctrl+Y).",
            """
Redo replays the command that was undone last. Doing anything new clears the redo
branch, as usual.

A command that is redone re-applies the *same* inputs it was given (the same
offset, the same description, the same file); it does not re-read anything from
disk.
""",
            "edit.undo",
        ),
        "edit.delete": _t(
            "Edit → Delete",
            "Edit and tools",
            "Remove the selected nodes and elements, and what hangs from them.",
            """
Deletes the selection. Deleting a **node** also removes the elements that use
it, and the loads and constraints that pointed at it: leaving a dangling
reference makes the model invalid and the next run refuses it.

- Deleting a node that a member needs is refused rather than silently cutting
  the member, when the member is not itself selected.
- The deletion is one command: Ctrl+Z restores the nodes, elements, loads and
  constraints together.
- To remove a duplicate, look at Edit → Check Model for Duplicates first: it
  merges instead of deleting, which keeps the loads and restraints.
""",
            "edit.check_duplicates",
            "edit.clear_selection",
        ),
        "edit.clear_selection": _t(
            "Edit → Clear Selection",
            "Edit and tools",
            "Deselect everything (Esc does the same in the viewport).",
            """
Empties the selection. Most Assign commands need a selection, so this is how you
start a different one. The tools also clear the selection when they finish.
""",
            "edit.select_all",
        ),
        "edit.select_all": _t(
            "Edit → Select All",
            "Edit and tools",
            "Select every node and element in the model.",
            """
Selects everything, which is what a bulk Assign command (a section, a material,
a restraint) needs. On a large model this also means every glyph changes state;
the canvas redraws once.
""",
            "edit.clear_selection",
            "select.menu",
        ),
        "edit.table_editing": _t(
            "Edit → Interactive Table Editing",
            "Edit and tools",
            "Joints, elements and joint loads as spreadsheets: edit, paste, add, delete.",
            """
The model as tables, SAP2000's interactive database editing (Ctrl+T). Nothing
changes until **OK**, which checks every cell and every reference and applies
all the tabs as one undo step. A bad cell keeps the window open and names its
table, row and column.

# Tabs
- **Joints** — ID, name, coordinates, restraints and masses. Only the DOFs the
  model has are columns: a 2D frame shows X, Z, Ux, Uz, Ry. Restraints are **1**
  (fixed) or **0** (free); yes/no and x also work. A new row with an empty ID
  gets the next free joint number.
- **Elements** — name, joints (space separated, i then j), section and material.
  The type is read only, and elements are not added here (draw them or use a
  wizard); rows can be deleted.
- **Joint Loads** — one row per load: the Plain pattern (its name or id), the
  joint and the force components. Add rows to load more joints.

# Spreadsheet keys
- **Ctrl+C** copies the selected cells as tab-separated text, **Ctrl+V** pastes
  a block from Excel or LibreOffice at the current cell and adds the rows it
  needs (Joints and Joint Loads). Read-only columns are skipped.
- **Delete** clears the selected cells; **Delete Rows** removes whole rows.
- A decimal comma is read as a point.

# Notes
- Deleting a joint that an element, a constraint or a load still uses is refused
  at OK; delete those first or delete the joint from the canvas (which takes its
  elements with it).
""",
            "edit.select_all",
            "select.menu",
        ),
        "select.menu": _t(
            "Select menu",
            "Edit and tools",
            "Select by element type, section, material or load pattern, invert, or go back.",
            """
Every entry **adds** to the current selection, so two queries in a row select
both sets: the frames of section A, then those of section B. Start from Clear
Selection (Esc) to pick one set alone.

# Entries
- **Invert Selection** (Ctrl+I) — selects every joint and element that is not
  selected, and drops the ones that are.
- **Get Previous Selection** (Ctrl+P) — goes back to what was selected before
  the last change; pressing it again swaps back.
- **All Joints / All Elements** — one kind only; Select All (Ctrl+A) takes both.
- **By Element Type / Section / Material** — the submenus list what the model
  uses, with a count. A material is found wherever an element reaches it: its
  own material fields, or the fibres, patches and layers of its section.
- **By Load Pattern** — the joints and elements a pattern loads. A pattern with
  a self weight loads every frame whose section has a unit weight.
- **By Group** — the joints and elements of a group (Define → Groups).
- **Supported Joints**, **Joints with Mass**, **Elements with Self Weight**
  (frames, trusses and shells).
- **Loose Joints** — joints no element, constraint, rigid link or diaphragm uses.
  **Joints Inside Members** — joints lying inside a frame or truss without being
  one of its ends, with those members (fix them with Edit → Divide Frames at
  Joints). **Joints on Shell Edges** — joints inside a shell edge, not at a
  corner, with those shells (subdivide the shells with Edit → Mesh). The three
  use the duplicates check's tolerance, a millionth of the model's size.
- **Joints of Selected Elements** — the end joints of what is selected;
  **Elements between Selected Joints** — the elements whose every joint is
  selected.
""",
            "edit.select_all",
            "edit.clear_selection",
            "edit.divide_frames",
        ),
        "edit.merge_joints": _t(
            "Edit → Merge Joints",
            "Edit and tools",
            "Joints closer than a tolerance become one.",
            """
For a drawing whose joints are a few millimetres apart where they should be one
(an imported DXF, two frames drawn separately): they look connected and are
not, and the model solves as two pieces.

# Values
- **Tolerance** — joints closer than this merge. It starts at a thousandth of
  the model's size; Check Model for Duplicates uses a millionth, for joints that
  are meant to be exactly coincident.
- **Apply to** — the selected joints only (only they merge, among themselves),
  or the entire model.
- The summary says how many groups merge and how many joints go before you
  accept, and which groups are left alone.

# What happens
- The lowest id of a group stays, at its own position. Elements, loads,
  constraints and groups that used the others move to it; a DOF restrained on
  any of them stays restrained, and different masses are added.
- Members that become repeated (two beams on the same two joints) are removed,
  and their loads move to the one that stays.
- A group joined by a zero-length element, an equalDOF, a rigid link or the
  retained joint of a diaphragm is meant to be coincident and is left alone.
- One undo step.
""",
            "edit.check_duplicates",
            "edit.divide_frames",
        ),
        "edit.divide_frames": _t(
            "Edit → Divide Frames at Joints",
            "Edit and tools",
            "Split frames and trusses at the joints that lie inside them.",
            """
A column whose top lands in the middle of a beam, or a brace that ends on a
girder, looks connected on screen; unless the beam has a joint there, the
column passes by and the beam does not carry it. This splits every member at
the joints lying on it, so they are connected.

# Values
- **Tolerance** — how close a joint has to be to a member to count as lying on
  it (a thousandth of the model's size to start with).
- **Apply to** — the selected members, or the entire model.
- **Also split members where they cross each other** — two members crossing
  with no joint get one there, shared by both.

# What happens
- Each member becomes pieces between its joints; the pieces keep the section,
  material and assignments, distributed loads and self weight follow them and a
  point load goes to the piece it falls on. One undo step; the new pieces are
  left selected.
- The summary also reports **loose joints** (on no element) and **joints on a
  shell edge** that is not at a corner. Those are not split here: select them
  from the Select menu, delete the loose ones, and subdivide those shells with
  Edit → Mesh so a corner lands on the joint.
""",
            "edit.merge_joints",
            "edit.mesh",
            "select.menu",
        ),
        "edit.move": _t(
            "Edit → Move",
            "Edit and tools",
            "Translate the selected nodes or members in place by (dx, dy, dz).",
            """
Moves the selection, and with it every element that uses those nodes: this is
the transform that changes the model rather than copying it.

Selecting a member is enough: its joints move with it, so you do not have to
pick the nodes first. A joint shared with a member you did not select moves as
well, and that member follows its joint.

# Values
- **dX, dY, dZ** — the displacement, in project units. Positive X is to the
  right, positive Z is up.

Moving a node changes the geometry of every member that touches it, and no
property follows it — the section, the material and the loads stay where they
were. To repeat a part of the model somewhere else, use Replicate.
""",
            "edit.replicate",
            "edit.mirror",
        ),
        "edit.replicate": _t(
            "Edit → Replicate",
            "Edit and tools",
            "Copy the selection N times, each copy offset by (dx, dy, dz).",
            """
The classic "copy this frame to the next axis" command, and the way a 2D portal
becomes a 3D building: select the frame, offset by the frame spacing along the
ridge direction, and repeat.

# Values
- **dX, dY, dZ** — the offset between consecutive copies. The default dZ of 3 is
  a storey height; for a building along Y, set dY and zero the others.
- **Number of copies** — how many, each at 1×, 2×, … the offset.

# What comes with the copy
- Nodes keep their **restraints and masses** (they are node fields).
- The **loads** on the copied nodes and elements are re-created for the copies:
  a copied loaded floor comes back loaded. Loads that were already copies are
  not doubled.
- **Ground motions are not copied**: copying a frame must not multiply a base
  motion.
- Only elements whose nodes are *all* in the selection are copied; a member that
  hangs outside the selection is skipped, not cut.
""",
            "edit.move",
            "edit.mirror",
            "define.portal_frame",
        ),
        "edit.mirror": _t(
            "Edit → Mirror",
            "Edit and tools",
            "Copy the selection reflected across a global plane (XY, YZ or XZ).",
            """
Like Replicate, but the copy is reflected rather than translated: the way to
build a symmetric structure from half of it.

# Values
- **Plane** — the mirror plane. `YZ` flips X, `XZ` flips Y (the usual one for a
  plan symmetry in a Z-up model), `XY` flips Z.

Reflection reverses the winding of a face element, so a shell or quad that is
mirrored has its normal reversed relative to the original. For a plate that
matters only if a pressure or a one-sided property depends on it.
""",
            "edit.replicate",
            "edit.move",
        ),
        "edit.mesh": _t(
            "Edit → Mesh",
            "Edit and tools",
            "Subdivide members and shells, and join the mesh up.",
            """
# What it does
- **Bars** longer than the target become equal pieces (a 10 m bar at 3 m becomes
  four elements of 2.5 m). The pieces inherit the section, the material and the
  element's own fields, and a distributed load follows them: each piece carries
  the same `q`, not a third of it.
- **Shells** larger than the target are subdivided ``m x n`` in their own natural
  coordinates, so a general quadrilateral is meshed without leaving its own
  edges, the winding (which the shell's normal depends on) is preserved, and two
  meshed shells of the same size share their common edge.
- **The joins** are what make the mesh usable: a bar is split at every node that
  lies on it (a column whose top lands in the middle of a beam, a frame drawn
  across a slab edge), and bars are split where they cross each other, so a
  crossing becomes a shared node instead of two members passing by.

# Values
- **Target size** — the longest edge a piece may have, in project units. It
  defaults to a tenth of the model (or of the selection).
- **Mesh** — the selection, or the whole model.
- **Tolerance** — how close a node has to be to a bar to count as lying on it, and
  how close two bars have to be to count as crossing. One part per million of the
  model is the default; loosen it for a drawing that was not drawn exactly.
- The summary under the form says what the mesh will add and replace before you
  accept it. A mesh that would add thousands of elements is one keystroke away
  from one that adds ten.

# Mechanics
Meshing changes the *discretisation*, not the structure: for a linear elastic
model, splitting a prismatic member does not change the answer (the test suite
checks a cantilever's tip deflection and a uniformly loaded beam before and
after). What it buys is resolution where the response varies — a plastic hinge, a
shell's bending — and what it costs is degrees of freedom.
""",
            "edit.check_duplicates",
            "mechanics.fiber_sections",
            "mechanics.shells",
        ),
        "edit.check_duplicates": _t(
            "Edit → Check Model for Duplicates",
            "Edit and tools",
            "Find — and merge — nodes that sit on top of each other and members defined twice.",
            """
A model that has been copied or imported twice accumulates coincident nodes and
repeated members, and neither is loud: the analysis runs, the deformed shape
looks right (a copy doubles the stiffness **and** the load), and only the
reactions and the member forces are wrong.

# What it reports
- **Coincident nodes** — groups at the same point, with the tolerance you set
  (default: one part per million of the model's size, so metres and millimetres
  need no different numbers).
- **Duplicate elements** — the same type, the same nodes and the same
  properties. These are the ones that double a stiffness.
- **Parallel elements** — the same nodes with different properties. That can be
  deliberate, so it is reported and not touched.

# What it refuses to touch
The two nodes of a **zero-length element or a bearing**, and nodes tied by an
**equalDOF** constraint, are deliberate coincidences: merging them would delete
every isolator and every modelled hinge. They are listed with the reason.

# What the repair does
- Merges into the lowest node id, **combining restraints** (a support is never
  released by accident) and keeping equal masses once (a copy must not weigh
  twice) while adding masses that differ.
- Repoints element nodes, equalDOF constraints, nodal loads and imposed-support
  node lists to the node that stays.
- Removes duplicate members and the ones left with no length, and drops loads
  that were copies instead of doubling them.
- Recomputes element duplicates **after** merging the nodes, because merging two
  nodes can turn two members into the same member.

One undo step takes the whole repair back.
""",
            "edit.replicate",
            "file.import_dxf",
        ),
        "tools.select": _t(
            "Tools → Select",
            "Edit and tools",
            "The default tool: click to select, drag a box, middle-drag to orbit, wheel to zoom.",
            """
Clicking a node or an element **adds** it to the selection, so building one is
just clicking; Ctrl+click takes an item out, and clicking empty space clears the
lot. Dragging with the left button draws a box: dragged **downwards** it takes
only what is fully inside; dragged **upwards** it also takes what the box
touches, so a member that crosses it is picked. A box never selects a node or an
element that is hidden in that viewport. The camera turns with a
middle-button drag, which the left button no longer does.

With nothing else active this is also what unlocks the model for inspection:
hovering an element shows its properties, and the property dock follows the
selection.

# Editing several at once
With more than one thing selected, the Properties panel edits what they share.
Joints: the restraints (a box that differs between the joints shows a partial
check and is left alone) and the six lumped masses. Elements: type, section,
material, area, geometric transformation, integration rule and points, end
offsets, rigid-zone factor and cardinal point, each applied to the selected
elements that have it (an area to the trusses, a section to the frames). A value
the selection shares is shown as it is; one that differs shows **(varies)** and
keeps each item's own value unless you change it. **Apply to N joint(s)** and
**Apply to N element(s)** send only what you changed, as one undo step.
""",
            "tools.draw_node",
        ),
        "tools.draw_node": _t(
            "Tools → Draw Node (F4)",
            "Edit and tools",
            "Place nodes by clicking grid intersections.",
            """
Each click creates a node at the grid intersection under the cursor (or reuses
the node already there). The grid has to be visible: if the project has none,
Define → Coordinate System/Grids offers to create one, because a canvas that
rejects every click looks broken rather than empty.

- Snapping follows the **working plane** (the level chosen in View → Top/Front/
  Right): only that level's lines and intersections are active.
- The nodes are created in one command each, so Ctrl+Z removes them one at a time.
- *F4*, not F1: **F1 is the contextual help** everywhere in the application.
""",
            "define.add_node",
            "define.grid",
        ),
        "tools.draw_frame": _t(
            "Tools → Draw Frame (F2)",
            "Edit and tools",
            "Click two points to draw a beam-column between them.",
            """
The first click is one end, the second the other; each may be an existing node
or a grid intersection (a node is created if there is none there). The view locks
to the working plane while the tool is active, so clicks land where you expect.

- If the project has no section yet, a default elastic section is created with
  the member, in the same undo step.
- The result is an `ElasticBeamColumn`. To make it force-based or
  displacement-based, or to give it hinges, use Assign → Frame afterwards.
""",
            "tools.draw_truss",
            "assign.section",
        ),
        "tools.draw_truss": _t(
            "Tools → Draw Truss (F3)",
            "Edit and tools",
            "Click two points to draw a pin-jointed bar.",
            """
Draws a `TrussElement`: it carries axial force only and has no moment
connection. Use it for bracing and for genuinely pin-jointed members.

- The bar points at a **material** and an area, not a section. If the project has
  no uniaxial material, a default elastic one is created with the bar.
- In a 3D model a truss contributes stiffness only along its axis; a node that
  only touches trusses needs its other DOF restrained or it will be a mechanism.
""",
            "tools.draw_frame",
            "concepts.model",
        ),
        # ──────────────────────────── Define ────────────────────────────
        "define.grid": _t(
            "Define → Coordinate System/Grids",
            "Define",
            "The reference lines, and the coordinate systems they live in.",
            """
Grids are drawing aids: they snap the draw tools and give you levels to work at.
They do not create nodes by themselves (unless you ask the dialog to).

# Values
- **Coordinate system** — a name, an origin and a rotation. `Global` is at the
  world origin with identity rotation and cannot be deleted.
- **System type** — *Cartesian* (X, Y and Z lines) or *Cylindrical* (radial):
  the three tabs become **R** (rings: radii about the system's local Z axis),
  **T** (radial lines: angles in degrees from local +X towards +Y) and **Z**
  (levels). Rings close into full circles when the radial lines go all the way
  round (e.g. 8 lines at 45°), otherwise they are arcs between the first and
  last angle. The draw tools snap to the ring × radial-line crossings.
- **Grid lines per axis** — each line has an id (its label), an ordinate,
  Primary/Secondary, visibility, the end its label is shown at (**Start**,
  **End** or **Both**) and a colour. The ordinates are what the tools snap to; a
  line whose Visibility is off is neither drawn nor snapped to.
- **Add Row** continues the grid: the new line goes one *last spacing* beyond
  the last line (lines at 0, 6, 12 → 18) and takes the next id (X3 → X4, C → D,
  Z → AA). Edit it if that is not where you want it.
- Lines are per axis: X lines are planes of constant X, and so on.
- **Hide All Grid Lines** — the system is neither drawn nor snapped to (the same
  switch as View → Show Grids and the right-click menu).

# Grid labels
- **Show grid labels** — the bubbles at the ends of the lines.
- **Content** — `ID` (A, 1, X3), `ID + coordinate` (`A (6)`) or `Coordinate`.
  A radial line shows its angle with a degree sign.
- **Size** (points) and **Colour** of the label text.
- **Position** + *Apply to all lines* — put every label at the Start, the End or
  Both ends at once (each row can still be changed on its own).
- Z levels are labelled once, beside the first corner of the plan.

# Working plane
- View → Top (XY), Front (XZ) or Right (YZ) chooses which pair of axes is the
  drawing plane, and the Level combo chooses which level of the third axis is
  active. A cylindrical grid offers its Z levels in plan (Top) only.
""",
            "tools.draw_node",
            "file.new_2d_frame",
            "define.grid_wizard",
            "view.grids",
        ),
        "define.grid_wizard": _t(
            "Define → Grid Wizard",
            "Define",
            "A whole Cartesian or radial grid from a few numbers.",
            """
For a regular grid you do not want to type line by line. One undo step.

# Values
- **Put it in** — a new coordinate system, or *Replace the grid of* an existing
  one (its origin and rotation are kept). A new project's empty Global grid is
  offered first.
- **New system name** and **Origin** — only for a new system.
- **Grid type** — *Cartesian* (X lines, Y lines, Z levels) or *Cylindrical*
  (rings by radius, radial lines by angle in degrees, Z levels). A 2D model is
  Cartesian in the X-Z plane, so its Y row is off.
- Per row: **Number** of lines (0 = none on that axis), **Spacing**, where the
  **First** line is, and the **Names**: `A, B, C …`, `1, 2, 3 …` or `X1, X2 …`.
- **Labels** — on/off, content (ID, ID + coordinate, coordinate) and position
  (Start, End, Both); size and colour are in the grid dialog.

The preview lists the lines before anything is created. Rings need radii of 0 or
more, and the radial lines cannot go past a full turn: 8 lines at 45° close the
circle, 9 would put two on top of each other.

Afterwards, Define → Coordinate System/Grids edits any line one by one.
""",
            "define.grid",
            "tools.draw_frame",
        ),
        "view.grids": _t(
            "View → Show Grids / Show Grid Labels",
            "View",
            "Hide or show the grids and their labels, also from the right-click menu.",
            """
- **Show Grids** — draws (or hides) every coordinate system's grid. A hidden grid
  is not snapped to either, so the draw tools then land on the working plane.
  It is the same switch as *Hide All Grid Lines* in the grid dialog, it is saved
  with the model and Ctrl+Z undoes it.
- **Show Grid Labels** — the line ids/coordinates at the ends of the lines.
- **Right-click** on the model view (a click, not a drag: a right drag zooms)
  with **nothing selected** opens the same switches, plus *Grids by system* to
  hide one coordinate system and keep the others, the grid dialogs, Grid Line
  View and the standard views.
- With **something selected** the right-click lists what can be done to it
  instead: the line at the top says what is selected; joints get the
  Assign → Joint options (restraints, masses, springs, constraints, loads,
  links…), frames the Assign → Frame options (section, releases, offsets,
  modifiers, member loads, hinges), shells the Area loads — directly when only
  one kind is selected, in a submenu per kind when several are — then Assign to
  Group, Move, Replicate, Mirror, Delete and Clear Selection. Press Esc or click
  empty space to clear the selection and get the grid menu back.

The menu ticks show whether at least one grid (label) is visible.
""",
            "define.grid",
            "define.grid_wizard",
        ),
        "view.grid_line_view": _t(
            "View → Grid Line View",
            "View",
            "Only the objects lying on one grid line, looked at face on.",
            """
Pick a grid line by its label — `Global: X A (6)`, `Global: Z Z2 (3)`, or a ring
or radial line of a cylindrical grid — and the view keeps only the joints within
the **window** either side of it and the elements all of whose joints are kept.
Everything else is hidden from the view (not from the model: the analysis and
the tables still see all of it).

# Values
- **Grid line** — every line of every coordinate system, by system, axis, id and
  ordinate.
- **Window either side** — how far from the line a joint may be, in the model's
  length unit. Default **50 mm** (0.05 in a model in m, 50 in mm, converted for
  ft and in). The dialog remembers the last value and counts what will be shown.

# What the view does
- An X line is looked at from the Right (YZ), a Y line from the Front (XZ) and a
  Z level from the Top (XY), with that line as the working plane, so you can
  draw on it straight away. A ring or radial line keeps the isometric view.
- The filter follows the model while you work: a member drawn on the line
  appears, one moved off it disappears. The status bar says what is shown.
- **View → Show All Objects** (or the right-click menu) brings everything back.
  Opening another project does too.
""",
            "view.grids",
            "define.grid",
        ),
        "define.add_node": _t(
            "Define → Add Node",
            "Define",
            "Add one node by typing its coordinates.",
            """
# Values
- **X, Y, Z** — the coordinates in project units. In a 2D project only X and Y
  are used.
- **Restraints** — which DOF are fixed at the node (the same dialog as
  Assign → Joint → Restraints).
- **Snap to grid** — fills the coordinates from a grid intersection instead of
  typing them.

Typing coordinates is the way to place a node that is not on a grid line, and
the way to check a coordinate you are unsure about.
""",
            "assign.support",
            "define.grid",
        ),
        "define.create_shell": _t(
            "Define → Create Shell from 4 Nodes",
            "Define",
            "A four-node shell element from four selected nodes.",
            """
Select exactly four nodes and a plate section, and the command builds a
`ShellMITC4`. Walls, slabs and shear walls are shells.

- The **winding** is derived from the coordinates: a click selection has no
  order, and a face built from a scrambled list is inverted or twisted. The
  order is taken counter-clockwise about the face's normal (the best-fit plane
  of the four points), and a selection that cannot form a face — coincident,
  collinear, or with one point inside the triangle of the others — is refused
  with the reason.
- The **plate section** carries E, ν, the thickness and the density. OpenSees
  wants a section for a shell, not a material: the thickness is the section's
  business.
- If the project has several plate sections you are asked which one.
""",
            "define.section_library",
            "mechanics.shells",
        ),
        "define.portal_frame": _t(
            "Define → Create Portal Frame",
            "Define",
            "The wizard, on the project that is already open.",
            """
The same wizard as File → New 2D Frame, but it builds into the current project
and **does not** add a grid: the grid belongs to the New 2D Frame flow, where
the wizard is the whole point of the menu entry. Here it adds to a model you are
already working on — a second bay, an annex, a frame inside an existing 3D model.

# Values
See **File → New 2D Frame**: bays and bay width, eave height, roof type and
slope, the two sections, the support condition, the plane and origin, and
whether to restrain the out-of-plane DOF.
""",
            "file.new_2d_frame",
            "mechanics.static",
            "define.truss",
        ),
        "define.truss": _t(
            "Define → Create Truss",
            "Define",
            "A simply supported plane truss from a few numbers.",
            """
Builds the nodes and the `truss` bars of a plane truss into the open project,
as one undoable step, and leaves it selected.

# Values
- **Type** — **Pratt** (verticals, diagonals running down towards mid-span:
  in tension under gravity), **Howe** (diagonals running up: in compression),
  **Warren** (no verticals, diagonals zig-zag to top nodes at mid-panel) or
  **Warren with verticals**.
- **Span**, **Panels** and **Depth at mid-span**.
- **Top chord** — parallel to the bottom chord, **pitched** to a ridge at
  mid-span (with its own depth at the supports), or **triangular** (closed at
  the supports). A pitched truss needs an even number of panels so a panel
  point sits at the ridge; a pitched Warren an odd number, so a top node does.
- **Material** and the **chord** and **web** areas. With no uniaxial material
  in the project, a default elastic steel is created with the truss.
- **Plane**, **Origin**, and whether to restrain the out-of-plane translation.

# Mechanics
The left end is pinned and the right end on a roller, so the truss is
statically determinate externally. A truss bar has no bending stiffness, so in
a frame model (ndf 3 or 6) the rotations of every truss node are restrained;
connect it to frames afterwards only through nodes you free again. The bars
take the **unit weight** on the Members page (steel by default), so the DEAD
case carries them: half of each bar's weight goes to each of its joints.
""",
            "define.portal_frame",
            "mechanics.static",
        ),
        "define.material_library": _t(
            "Define → Material Library",
            "Define",
            "The uniaxial and nD materials the model can use.",
            """
Materials are the constitutive laws the elements and fibre sections point at.

- **From library…** inserts a *typical construction material*: specified concrete
  strengths (f'c from 17 MPa up, with ACI's 0.002 and 0.003 strains), the
  reinforcing grades ACI permits (280, 420, 550 and A706's 690), the structural
  steels AISC tabulates (A992, A36, A572 Gr. 50, A500 Gr. B) and masonry at its
  usual specified strengths (Em = 700 f'm for clay masonry, 900 f'm for concrete
  block). Each row names the clause it comes from, and the picker shows the
  published value beside the one that will be inserted, converted to this
  project's units. Masonry enters as an elastic material: an existing wall's
  nonlinear backbone is a per-building decision, not a table lookup.
- **Uniaxial** (used by trusses, zero-length elements, links and fibre sections):
  `Elastic`, `ElasticPP`, `Hardening`, `Steel01`, `Steel02`, `Concrete01`,
  `Concrete02`, `Concrete04`, `Hysteretic`, `HystereticSM`, and through one
  generic form, in the order and with the names of the OpenSeesPy manual:
  - steel and concrete: `ReinforcingSteel`, `Concrete06`, `Concrete07`,
    `ConcreteCM` (Chang-Mander: Tsai's envelope in compression and tension,
    cyclic rules for RC under earthquake loading; `-GapClose` 1 closes cracks more
    gradually);
  - deterioration (plastic hinges): `ModIMKPeakOriented`, `ModIMKPinching`,
    `Bilin`, `Pinching4` (a symmetric envelope);
  - dampers and rate models: `ViscousDamper`, `BilinearOilDamper`, `Viscous`,
    `BoucWen`. A dashpot answers the strain rate, so it acts only in a
    transient case: put it in a zero-length or link element, in `Parallel`
    with the spring it damps. Keep a `ViscousDamper`'s `K_el` realistic: when
    Cd / K_el is some 1e5 times shorter than the time step its internal
    integrator fails;
  - multilinear and gaps: `ElasticBilin`, `ElasticPPGap` (no force until the
    gap closes, then elastic up to Fy and plastic, the plastic strain widening
    the gap; Fy and gap of one sign, negative for a compression gap),
    `MultiLinear`, `ElasticMultiLinear` (a table of strain-stress points);
  - pile springs: `PySimple1`, `TzSimple1`, `QzSimple1`;
  - wrappers of other materials: `Parallel` (stresses added, optional factors),
    `Series` (strains added), `MinMax` (failure outside a strain range),
    `InitStrainMaterial`, `InitStressMaterial`, `Fatigue`. A wrapper is emitted
    after what it wraps, whatever the list order, and a missing or circular
    reference is reported before the run.
- **nD** (plane elements and shell layers): `ElasticIsotropic`, `J2Plasticity`,
  `PlasticDamageConcretePlaneStress`, and the plate wrappers a layered shell needs:
  `PlateFiber` (of a 3D material), `PlateFromPlaneStress` (of a plane-stress
  concrete, with its out-of-plane shear modulus) and `PlateRebar` (a uniaxial
  steel at an angle).

Every form row shows the parameter's OpenSees name and meaning; each material is
checked against the live solver, and the Material Tester runs any uniaxial one
(a wrapper together with what it wraps).
- A **catalog material** puts one of the gidopensees presets into the project
  with its unit-carrying defaults read out of the schema; the ones whose
  behaviour could not be verified against the solver refuse to be emitted rather
  than guess.

# Values that matter most
- `Steel02`: `Fy` (yield), `E0` (initial modulus), `b` (post-yield slope as a
  fraction of E0), and optionally `R0`, `cR1`, `cR2` for the transition curve.
- `Concrete04`: `fpc` (compressive strength, negative), `epsc0` (strain at
  peak), `fpcu`/`epsU` (crushing), and the Popovics parameters. For a confined
  core, use the confined strength and strain.
- `Elastic`: `E`. Everything else follows from the section.
""",
            "define.section_library",
            "mechanics.fiber_sections",
            "define.material_tester",
        ),
        "define.friction_library": _t(
            "Define → Friction Models",
            "Define",
            "The friction laws the sliding bearings use.",
            """
Isolators that slide need a friction model; elastomeric bearings do not.

- **Coulomb** — a constant coefficient μ. The simplest, and adequate when the
  sliding velocity is low.
- **VelDependent** — μ depends on the sliding velocity (a lubricated or PTFE
  interface heats up and changes as it moves).
- **VelNormalFrcDep** — μ depends on the velocity *and* on the normal force, for
  bearings whose normal force changes during the motion.

A bearing points at a friction model by id; the model's parameters are shared,
so changing one changes every bearing that uses it.
""",
            "assign.bearing",
            "mechanics.isolators",
        ),
        "define.material_tester": _t(
            "Define → Material Tester",
            "Define",
            "Run one material through a strain protocol and see its curve.",
            """
A single material, loaded in an isolated model by a prescribed strain history,
with the stress-strain response plotted. It answers "what does this material do"
before you trust it inside a section.

# Values
- **Material** — any defined uniaxial material.
- **Protocol** — monotonic to a strain, or cyclic with an amplitude and a number
  of cycles. The strain rate is irrelevant for these rate-independent laws.
- It uses the same emitters as the analysis runner, so a material cannot behave
  one way in the tester and another way in a model.
""",
            "define.material_library",
            "mechanics.fiber_sections",
        ),
        "define.ground_motions": _t(
            "Define → Ground Motions",
            "Define",
            "The record library: files, formats, units and metadata.",
            """
Records are stored in the project **by reference** (a path and a content hash),
so a project stays small and a changed file is detected. Everything a case needs
about a record is computed once, here.

# Values
- **File and format** — PEER `.AT2`, two-column (time, acceleration) or
  single-column (with the time step supplied).
- **Acceleration unit** — `g` or the project's acceleration unit; the factor is
  stored with the record.
- **Metadata** — PGA, PGV, PGD, Arias intensity and the 5-95 % significant
  duration, computed from the samples: useful to choose and to document records.
- **Scaling** — by PGA or by Sa(T1) of a chosen period; a response-spectrum case
  can also compute the factors that match a target spectrum over a period range.
""",
            "mechanics.spectra",
            "mechanics.ground_motions",
            "define.linear_ts",
        ),
        "define.section_designer": _t(
            "Define → Section Designer",
            "Define",
            "Draw any cross-section, or import it from a DXF, and add it as an elastic or fibre section.",
            """
For a section no library has: a built-up girder, a shape with openings, a
precast profile, a section drawn in CAD. The section is a list of **regions** —
polygons and circles, each solid or a **hole** — in the local (y, z) plane: y up
the depth, z across, lengths in the project's unit.

# Drawing
Type a command and press Enter (the buttons type one for you; edit the numbers
before running it):

- `rect W H [Y Z]` — a rectangle W wide by H deep, centred at (Y, Z);
- `circle D [Y Z]`;
- `poly Y1,Z1 Y2,Z2 Y3,Z3 ...` — a polygon through its vertices;
- `ishape D BF TF TW`, `channel D BF TF TW`, `tee D BF TF TW`, `angle D B T`,
  `tube W H T`, `pipe D T`, each with an optional `Y Z`;
- `hole <shape> ...` — any shape as a hole (`hole circle 0.1 0 0.05`);
- `move N DY DZ`, `delete N` (N is the number in the list, or `last`),
  `center` (centroid to the origin), `clear`.

**Undo** steps back one command; **Solid / hole** flips the selected region.

# Import DXF
Reads the closed outlines of a drawing: closed polylines (arcs from bulges
included), circles, closed ellipses and splines; curves are flattened finely, a
circle stays exact. An outline inside another is a hole (inside two, solid
again). The drawing's X becomes z and its Y becomes y. `$INSUNITS` gives the
scale to the project's unit (a unitless file is taken as project lengths, and
the message says so); the section is then centred. Lines, open polylines and
text are counted and left out.

# Properties
Area, centroid, Iz = ∫y² dA and Iy = ∫z² dA about the centroid, the product
Iyz and the principal moments with their angle, elastic and plastic moduli,
radii of gyration, and the **torsional constant J**, solved for Saint-Venant
torsion on a grid (Prandtl stress function, hollow shapes included): within a
fraction of a per cent for compact and hollow shapes, a few per cent for thin
open ones. An unsymmetric section is noted: OpenSees' elastic section has no
Iyz, so its principal axes are not followed.

# What OK adds
- **Elastic section**: A, Iz, Iy, J and E with G = E / (2 (1 + ν)). Pick a
  material to copy its initial modulus, or type E.
- **Fiber section**: one uniaxial material on a grid of fibres (cells per side
  of the bounding box); each fibre sits at the centroid of the part of its cell
  inside the section, measured from the section's centroid, and the fibre areas
  add up to the exact area. GJ (for 3D members) starts at G J.
""",
            "define.section_library",
            "define.concrete_section",
            "file.import_dxf",
        ),
        "define.concrete_section": _t(
            "Define → Concrete Section Wizard",
            "Define",
            "A reinforced concrete section, its concrete and steel materials, from a few inputs.",
            """
Builds a reinforced concrete frame section the way it is drawn on a plan, and
adds the materials it needs, in one undo step. The drawing on the right shows the
concrete, the core inside the bar centrelines (dashed) and the bars at their true
size, with the centroid.

# Shape
- **Rectangle** (column or beam), **Circle** (column), **T-beam** (flange on
  top, centred on the web) and **L-beam** (edge beam, flange to +z).
- Depth h runs along local **y**, width b along local **z**: assign the section
  so local y is the direction the member bends in (Assign → Frame → Local Axes).

# Reinforcement
- Bar sizes **metric** (φ6 to φ40 mm) or **US** (#3 to #18).
- Top and bottom bars (at least two each) and intermediate bars on each side
  face; a circle takes its bars evenly around.
- **Clear cover** is to the outside of the ties: the bars sit at cover + tie +
  half a bar from the face.
- Tie size and spacing give the transverse ratio ρs (two legs each way for
  hoops, 4 Asp / (ds s) for a spiral), used for the confinement.

# Materials it adds
- **Cover concrete**: `Concrete02`, f'c at a strain 2 f'c / Ec (so its initial
  slope is Ec = 4700 sqrt(f'c) MPa, ACI 318-19), spalling to zero at 0.005,
  tension 0.33 sqrt(f'c) MPa.
- **Core concrete**: with **Confined core (Mander)** ticked, f'cc, εcc and εcu of
  Mander, Priestley and Park (1988) with ke = 0.75 for hoops and 0.95 for a
  spiral, εcu = 0.004 + 1.4 ρs fyh εsu / f'cc; otherwise the cover concrete.
- **Bars**: `Steel02` with fy, Es and 1 % hardening.
- **Concrete law** `ConcreteCM` (Chang and Mander 1994) instead of `Concrete02`
  for cyclic analyses: the cover peaks at εc = f'c^(1/4) / 1150 (MPa) with
  r = f'c / 5.2 - 1.9, the core at Mander's f'cc and εcc with
  r = Ec / (Ec - f'cc / εcc), which makes its envelope Mander's curve; tension
  0.33 sqrt(f'c) MPa at 1.2 ft / Ec with r = 1.2.

# Sections it adds
- **Fiber section** (default): core, cover strips, flange overhangs and bars as
  layers, for force- or displacement-based members. Its GJ is the gross elastic
  one (G = Ec / 2.4).
- **Elastic section with cracked inertia**: the gross area, Ec and I times the
  factor of ACI 318-19 Table 6.6.3.1.1 — **0.70 for a column, 0.35 for a beam** —
  for a linear model; change the factor if your code asks for another.

A column's longitudinal ratio outside ACI's 1 % to 8 % is noted. Edit the
materials afterwards in Define → Material Library, and the fibre layout in
Define → Section Library (double-click the section).
""",
            "define.section_library",
            "define.section_designer",
            "define.material_library",
        ),
        "define.section_library": _t(
            "Define → Section Library",
            "Define",
            "Elastic, nonprismatic, fibre, aggregated and plate sections, plus the AISC shapes.",
            """
Sections are what frame, shell and zero-length-section elements point at.

# Types
- **Elastic section** — E, A, Iz, Iy, G, J. What a linear frame analysis needs.
  Optional **shear areas As2 / As3** (0 = none) add shear deformation: an elastic
  beam-column on such a section runs as an `ElasticTimoshenkoBeam`
  (needs G; a 3D member needs both). OpenSees 3.8 loads that element with
  full-length uniform loads (and self weight) only, so point, partial and
  trapezoidal loads on it are refused, and it takes no `-release`: a released end
  uses the hidden-node route instead. The member deflects by
  `P L³ / (3 E I) + P L / (G As)` on a cantilever; the Property Modifiers' shear
  areas scale As2 / As3, and a multiplier of 0 turns shear deformation off.
- **Nonprismatic (tapered) section** - a table of segments, each running from one
  **elastic** section to another over an absolute length or a fraction of the
  member, with a linear, parabolic or cubic variation. Assigning it splits each
  member into its **Subdivisions** pieces (minimum 12, default 12) of ordinary
  elastic beam-columns; the section at each piece is interpolated from the
  segment's start and end sections (the drawn rectangle/I/pipe/tube dimensions
  are interpolated, so a rectangular depth taper follows its true cubic inertia).
  The pieces keep the frame's end releases, end offsets, insertion and
  modifiers, and every element load is split across them. Editing the template
  refreshes the section properties of members already built from it; changing
  the subdivision count keeps their existing piece count, so set the count
  before assigning the section (or re-import the model) when the topology must
  change.
- **Fibre section** - patches and rebar layers tied to uniaxial materials. It
  yields and cracks where the material does, and needs a non-linear case.
- **Section aggregator** — several responses (axial, bending, shear, torsion)
  combined into one section, each with its own material or section.
- **Plate section** (shell) — E, ν, thickness h and density ρ.
- **LayeredShell** (shell) — a table of layers, each a plate material and a
  thickness, from one face to the other: concrete layers (`PlateFromPlaneStress`
  of `PlasticDamageConcretePlaneStress`, or `PlateFiber`) and rebar layers
  (`PlateRebar` at 0° or 90°, thickness = bar area per unit width). At least three
  layers. OpenSees integrates each layer at its mid-plane, so n equal layers give
  1 - 1/n² of the bending stiffness: use several thin layers (10 or more) through
  a concrete wall or slab.
- **PlateFiber** (shell) — one plate material through the thickness h.

# AISC v16 shapes
"Add from AISC…" picks a shape by name (1,660 of them, 13 families). The values
are the published US-customary ones; the dialog shows the published value *and*
the converted one, and E and G remain your choice, because a shape is geometry,
not a material. The data comes from Steel Construction Manual values and was
cross-checked against an independent source before being committed.

Which inertia is strong depends on the project. A 2D frame bends in the x-y plane
about local z, so the table's strong-axis `Ix` becomes **Iz**. A 3D beam stands
with its depth along local z (local z is vertical for a horizontal member), so
gravity bends it about local y and `Ix` becomes **Iy**, with the table's `Iy` as
Iz. A fibre profile is turned upright the same way in 3D. The dialog's preview
shows the values it will insert. Sections inserted by builds before 0.0.11 into a
3D project have the two swapped: re-insert them, or swap Iy and Iz by hand.
""",
            "define.material_library",
            "mechanics.fiber_sections",
            "mechanics.shells",
        ),
        "define.function_ts": _t(
            "Define → Add Function TimeSeries",
            "Define",
            "Constant, Trig, Triangle, Rectangular or Pulse series.",
            """
A time series given by a formula instead of samples. The rows follow the type:

- **Constant** — the factor at every time (a load held in a transient).
- **Trig** — factor · sin(2π (t - t_start)/T + shift) + zero shift, between start
  and end (harmonic loads, a sine sweep step).
- **Triangle** — a triangular wave of period T, peak = factor, between start and end.
- **Rectangular** — the factor between start and end, zero elsewhere (a step held
  for a while).
- **Pulse** — rectangular pulses of period T, on for the width fraction of each
  period, between start and end (impacts, machine loads).

A static case steps time by its load increment, so these series also shape a
static load history. Checked against OpenSees' own evaluation.
""",
            "define.linear_ts",
            "define.path_ts",
        ),
        "define.multi_support": _t(
            "Define → Add Multi-Support Excitation",
            "Define",
            "Drive the selected supports with a displacement history (MultipleSupport).",
            """
Different supports moving differently — a long bridge, a pipe on two
structures — need the motion applied at the supports instead of as an inertial
load. Select the supports, then choose the direction, a **displacement** time
series and a factor. Each selected joint must be restrained in that direction:
the runner swaps its restraint for the imposed motion when the pattern runs.

Run it in a transient case. The velocity OpenSees also needs is derived from the
displacement series, which is what carries the motion into
stiffness-proportional damping of the elements.
""",
            "define.uniform_excitation",
            "define.path_ts",
        ),
        "define.custom_commands": _t(
            "Define → Custom OpenSees Commands",
            "Define",
            "OpenSeesPy calls for anything the application has no form for.",
            """
Each block is Python run while the model is built, in list order:

- **After the materials** — materials exist, sections and elements do not yet.
- **After the elements** — the whole model exists, before loads and analysis.

Names a block can use: `ops` (OpenSeesPy), `project` (read it, do not change it),
`ndm`, `ndf`, and `tag`, the first of the 1000 tags reserved for that block (from
1 000 000 up), so its objects never collide with the application's. A block that
raises stops the run with its name and the error; a block with a syntax error is
refused when you press OK. The exported OpenSees script contains the block's
commands.

# Safety
The code runs on this computer with your permissions. When you open a file that
contains enabled blocks, you are asked whether to trust them; answering No
disables them until you enable them here. Running a project file with the
command-line `python -m opensees_studio.run` runs its enabled blocks like any
script you run.

# Notes
- With an enabled block, the "no element stiffens this DOF" check is skipped
  (the block may add that stiffness); the solver itself still reports a
  singular model.
- Results are recorded only for the joints and elements of the model; an element
  a block adds shows up in the joints' displacements and reactions.
""",
            "define.material_library",
            "analyze.cases",
        ),
        "define.linear_ts": _t(
            "Define → Add Linear TimeSeries",
            "Define",
            "A load that ramps linearly with time: the default for a static case.",
            """
`Linear` goes from 0 to 1 over the case's time: with N steps, step k has
factor k/N. In a static case this is what a "load ramp in N steps" means, and it
is what a non-linear static case needs to follow the path.

Most of the time you do not create one by hand: a load pattern creates a default
linear time series when the first load is applied.
""",
            "define.plain_pattern",
            "mechanics.static",
        ),
        "define.constant_ts": _t(
            "Define → Time Series → Constant",
            "Define",
            "A load that stays at one factor for the whole case: a preload.",
            """
`Constant` keeps the pattern at the same factor through every step, so the
loads are there in full from the first step and do not ramp. Use it for a
preload (an axial force before a pushover, gravity before a transient) that
a later case continues from.

The dialog lists the project's Constant series; Add creates one with the
name and factor entered, Apply replaces the selected one, and Delete refuses
while a load pattern still refers to it.
""",
            "define.linear_ts",
            "define.plain_pattern",
        ),
        "define.path_ts": _t(
            "Define → Add Path TimeSeries",
            "Define",
            "A load or displacement read from a file or a record.",
            """
A path time series takes its values from a file (a ground-motion record, or any
two-column time series) and can be scaled by a factor.

- **File and column** — which file, and which column holds the values.
- **dt** — the file's time step, used when the file has no time column.
- **Factor** — multiplies every value; this is where a record's `g` becomes the
  project's acceleration unit, or where a scale factor is applied.
- Ground-motion records from the catalog are stored as path series with the file
  kept outside the project.
""",
            "define.linear_ts",
            "define.ground_motions",
            "mechanics.transient",
        ),
        "define.plain_pattern": _t(
            "Define → Add Plain Load Pattern",
            "Define",
            "A named group of loads, with the time series that drives it.",
            """
A `Plain` pattern holds the nodal loads and the distributed element loads
applied together, and points at a time series that scales them in time. Cases
reference patterns by id, so the same loads can be used by several cases.

- One pattern per load type (dead, live, wind, earthquake) is the usual
  arrangement: a static case can then combine them, and a transient can apply
  gravity first and the earthquake after `loadConst`.
- A load pattern with no loads is legal but does nothing.

# Self weight
- **Self-weight multiplier** — 1 adds the weight of every frame whose section
  has a **unit weight** (gamma, force per volume, set in the Section Library):
  gamma times A per unit length, downward (-Z, in 2D and in 3D), split over the
  member's local axes, so a column takes it axially and a sloped rafter partly
  axially. 0 leaves it out.
- A new project starts with a **DEAD** case: a time series, a pattern with a
  self-weight multiplier of 1 and a linear static analysis that runs it. The
  default section is steel (gamma = 77 kN/m³), so a frame drawn on a fresh
  model already has a gravity result. A **plate section** (shell) has a unit
  weight too: each ShellMITC4 takes gamma times h per unit area as consistent
  nodal forces over its real shape.
- A **fiber section** has a unit weight too, applied to its gross area (patches
  plus bars plus loose fibres: an RC section comes out heavier by its steel
  ratio, 1-3 %). An **aggregator** weighs what the section it wraps weighs.
- **Trusses** and **BeamWithHinges** members carry their own unit weight (in the
  Properties panel): a truss bar sends half its weight to each joint, a
  BeamWithHinges member takes gamma times its elastic area A per length.
  Assign → Frame → Hinge keeps the member's weight per length. 2D quads,
  zero-length elements, bearings and links carry no self weight.
""",
            "assign.load",
            "assign.distributed_load",
            "define.linear_ts",
        ),
        "define.uniform_excitation": _t(
            "Define → Add Uniform Excitation",
            "Define",
            "A ground motion applied to every support at once.",
            """
The usual way to run a time history: one acceleration record, applied in one
direction, at every restrained support.

# Values
- **Direction** — the DOF driven: 1 = X, 2 = Y, 3 = Z (vertical) in 3D; 1 = X and
  2 = Z (vertical) in a 2D model, which lives in the X-Z plane.
- **Record / series** — the acceleration series, and optionally its velocity and
  displacement; the application derives them from the acceleration if you do not
  supply them.
- **Factor** — the scale applied to the record.

# Mechanics
The excitation is applied as an inertial load (`-accel`), so the structure sees
the ground acceleration and the supports move with it. For supports that move
differently (a long bridge), use an imposed support motion pattern instead.
""",
            "mechanics.transient",
            "define.path_ts",
            "mechanics.ground_motions",
        ),
    }
)

TOPICS.update(
    {
        # ──────────────────────────── Assign: joints ────────────────────────────
        "define.load_combinations": _t(
            "Define → Load Combinations",
            "Define",
            "Factored sums and envelopes of the results of analysis cases.",
            """
A load combination combines the **stored results** of analysis cases; it never
runs a solver of its own. A combination can include Static and Response Spectrum
cases, and other combinations (an envelope of the strength combinations, for
instance). Each included case has a scale factor.

# The four types
- **Linear Add** — the factored sum, 1.2·DEAD + 1.6·LIVE. Superposition: valid
  only when the cases respond linearly.
- **Envelope** — the maximum and the minimum over the included cases, value by
  value. Valid for any case, linear or not.
- **Absolute Add** — the sum of the magnitudes.
- **SRSS** — the square root of the sum of the squares.

# Maximum and minimum
Every result has an upper and a lower value. A static case has one value (both
are the same); a response spectrum result is a peak, so it counts as plus and
minus that peak. A Linear Add of static cases therefore has one value; an
envelope, an SRSS, an Absolute Add, or anything that includes a spectrum has a
maximum and a minimum. With a negative scale factor the two swap.

Element forces are enveloped as **internal forces**, the sign the force diagram
draws, so the diagram of the maximum is the upper envelope of the case diagrams.
The results table lists each end force as OpenSees reports it (localForce), with
its maximum and minimum.

# What a combination contains
Only what every included case provides. A response spectrum case provides
displacements, reactions, element forces and shell resultants: each is the SRSS
or CQC of the response to the equivalent static load of every mode, a peak
magnitude, so it counts as plus and minus that peak. A spectrum result stored
before it had forces gives displacements only: run the case again.

# Warnings
A Linear Add, Absolute Add or SRSS that includes a case solved with an iterative
algorithm (Newton, …), or a model with P-Delta or corotational transformations,
is applied with a warning: adding nonlinear responses is not the response to the
added loads. Run the summed loads as one case instead, or use an Envelope.
Material nonlinearity is not detected.

# Running a combination
Analyze → Run lists the combinations after the cases. Running one runs only the
cases it needs that have no current results (in one analysis process), then
combines. A result stays current until the model changes; editing a combination
does not make results stale. Display → Show Results Of… switches between stored
results without running anything.

# Generating the combinations of a design code
**Generate from a design code…** adds the combinations of ASCE 7-16 (LRFD or
ASD), EN 1990 or TS 500 / TBDY 2018 from cases you tag with the load they carry:
Dead, Live, Roof live, Snow, Rain, Wind and Earthquake (the tag is guessed from
the case name). The result is an ordinary set of Linear Add combinations: edit,
copy or delete them. Wind and static earthquake cases are added in both signs; a
response spectrum case is already plus and minus, so it is added once. An
envelope over each generated group is added too (one per group, so the ultimate
and serviceability limit states of EN 1990 do not mix). Roles a code does not use
are named after the run.

**Create the missing load cases** (on by default) gives every load the code uses
that no case is tagged with an empty load case of its own before generating:
LIVE, ROOF LIVE, SNOW, RAIN, WIND X and WIND Y, EQ X and EQ Y (one wind and one
earthquake case along X in a 2D model), and DEAD with the self weight if there is
no dead case. Each is a Plain pattern with a linear time series and a linear
static case, all named after the load; the dialog lists what it would create.
Their patterns start empty: assign the loads before running. Undo removes the
cases and the combinations together.

The factors are the code's. Judgement stays yours: the occupancy-dependent
live-load reduction, favourable versus unfavourable permanent action, the
national annex.

**Earthquake: 100% + 30% orthogonal rule** applies to any code: with two or more
earthquake cases, each acts at 100% with the others at 30% (±Ex ± 0.3Ey and
±0.3Ex ± Ey).

## ASCE 7-16 LRFD (Section 2.3.1)
- 1.4D
- 1.2D + 1.6L + 0.5(Lr or S or R)
- 1.2D + 1.6(Lr or S or R) + (L or 0.5W)
- 1.2D + 1.0W + L + 0.5(Lr or S or R)
- 1.2D + 1.0E + L + 0.2S
- 0.9D + 1.0W
- 0.9D + 1.0E

The live-load factor in the last combinations is 1.0: the 0.5 exception depends
on the occupancy.

## ASCE 7-16 ASD (Section 2.4.1)
- D; D + L; D + (Lr or S or R); D + 0.75L + 0.75(Lr or S or R)
- D + 0.6W; D + 0.7E
- D + 0.75L + 0.75(0.6W) + 0.75(Lr or S or R); D + 0.75L + 0.75(0.7E) + 0.75S
- 0.6D + 0.6W; 0.6D + 0.7E

## EN 1990
- **Ultimate, equation 6.10**: 1.35G + 1.5Q1 + Σ 1.5 ψ0,i Qi, with each variable
  action (imposed, roof, snow, wind) leading in turn, and 1.35G alone. With
  *favourable permanent action* the set is repeated with 1.0G (uplift,
  overturning).
- **Seismic (accidental), 6.11b**: G + E + Σ ψ2,i Qi.
- **Serviceability**: characteristic G + Q1 + Σ ψ0,i Qi; frequent
  G + ψ1,1 Q1 + Σ ψ2,i Qi; quasi-permanent G + Σ ψ2,i Qi.

The ψ factors are those of Table A1.1: the *imposed load category* (A to H) sets
them for Live cases, roofs (Lr) are category H, wind is 0.6 / 0.2 / 0, snow is
0.5 / 0.2 / 0 (0.7 / 0.5 / 0.2 above 1000 m). Rain has no EN 1990 factors and is
not used.

## TS 500 / TBDY 2018
- 1.4G + 1.6Q
- G + nQ ± E and 0.9G ± E (TBDY 2018), with n the *live load participation* (1.0
  by default; Table 4.3 of the code gives 0.3 for housing and offices)
- G + 1.3Q ± 1.3W and 0.9G ± 1.3W (TS 500)

Roof live, snow and rain cases are not used. Check the factors against the
edition you design to.
""",
            "analyze.cases",
            "analyze.run",
            "display.select_results",
        ),
        "assign.support": _t(
            "Assign → Joint → Restraints",
            "Assign — joints",
            "Which degrees of freedom are fixed at the selected nodes.",
            """
A restraint removes a DOF from the unknowns: a fixed DOF carries a reaction
instead of a displacement.

# Values
- **Ux, Uy, Uz** — translations; **Rx, Ry, Rz** — rotations. A 2D model lives in
  the X-Z plane (Z up): in a 2D frame only Ux, Uz and Ry exist, in a 2D truss only
  Ux and Uz.
- **Presets** — pinned (translations fixed), fixed (everything), roller (one
  translation free), and so on. The check boxes are what is actually applied.
- The assignment **replaces** the restraints of the selected nodes.

# Mechanics
- Every unrestrained rigid-body direction has to be held somewhere or the
  stiffness matrix is singular and the run fails with a solver error. That is
  what "the model is unstable" usually means.
- A fixed rotation is a moment connection; leaving it free makes the connection
  a pin. In a portal frame that difference decides whether the frame sways like a
  frame or leans like a mechanism.
- A **spring support** is modelled with a zero-length element between the node
  and a fully fixed node, not with a restraint.
""",
            "mechanics.constraints",
            "assign.zero_length_section",
        ),
        "assign.springs": _t(
            "Assign → Joint → Springs",
            "Assign — joints",
            "Elastic support springs to ground on the selected joints.",
            """
A support spring ties a joint to the ground through a stiffness instead of a
fixed restraint: soil springs under a footing (Winkler), a flexible column base,
a bearing pad, or a lateral prop.

# Values
- One **k** per DOF of the model (a 2D frame: Ux, Uz, Ry), in force per length
  for a translation and moment per radian for a rotation, in the model's units.
  Zero means no spring. OK replaces the springs of every selected joint; all
  zero removes them.

# How it is analysed
- Each sprung joint gets a hidden ground node, fixed in every DOF, joined to it by
  a `zeroLength` element with one elastic material per sprung DOF, along the
  global axes.
- The spring force is reported as the joint's **reaction**, so the reactions
  still balance the loads. Springs also stiffen a modal analysis (a mass m on a
  spring k vibrates at √(k/m)).
- A DOF that is also restrained ignores its spring.
- The canvas draws a green zigzag under a sprung joint. IFC export writes the
  stiffness into the support's boundary condition.
""",
            "assign.support",
            "assign.masses",
        ),
        "assign.masses": _t(
            "Assign → Joint → Masses",
            "Assign — joints",
            "The lumped mass at the selected nodes.",
            """
# Values
- **mx, my, mz** — translational mass; **Ixx, Iyy, Izz** — rotational inertia.
  A mass of zero in a direction means that direction carries no inertia.
- Masses are what a modal or a transient case needs. A static case ignores them.
- Gravity is not a mass: an acceleration record acts on the mass (`-accel`), so a
  model with no mass has nothing for an earthquake to shake.

# Mechanics
- The period of a mode is T = 2π√(M/K): the mass you assign is the M half of
  that. Getting it wrong scales every period (and every spectral demand read at
  those periods).
- A common convention is to lump the seismic mass of a floor at its master node,
  which is also where equalDOF ties the floor together.
- Mass can also come from a section's `rho`, distributed over the element.
""",
            "mechanics.modal",
            "assign.equal_dof",
        ),
        "assign.equal_dof": _t(
            "Assign → Joint → equalDOF",
            "Assign — joints",
            "Make one node's DOF follow another node's.",
            """
The first node selected is the **retained** (master) node, the second the
**constrained** (slave), and the DOF you tick are the ones tied. Uses: a rigid
floor, a rigid link, a hinge made of two coincident nodes.

# Values
- **DOF numbers** — 1-based, in the order the model uses them. A 3D frame: 1 = Ux,
  2 = Uy, 3 = Uz, 4 = Rx, 5 = Ry, 6 = Rz. A 2D model lives in the X-Z plane: a 2D
  frame has 1 = Ux, 2 = Uz, 3 = Ry, a 2D truss 1 = Ux and 2 = Uz. The dialog lists
  the model's own.
- Ticking 1 and 2 on a pair of nodes at the same level is a diaphragm in plan.

# Mechanics
Tying DOF removes them from the unknowns: the constrained node's displacement is
whatever the retained node's is. It does not add stiffness anywhere else — a
rigid floor is also, physically, a constraint that distributes horizontal force,
which is exactly what this does.

A node takes one constraint, and constraints do not chain: a node an equalDOF
constrains may retain another equalDOF or rigid link only when its own equalDOF
ties every DOF. OpenSees' Transformation handler (every eigen analysis uses it)
solves any other chain, a node constrained twice, or a loop without an error
into wrong results, so the model check refuses them. Tie each node straight to
one retained node instead.

A frame end released at the constrained node is made without a further
constraint, as at a diaphragm joint (see Assign → Frame → Releases/Partial
Fixity).
""",
            "mechanics.constraints",
            "assign.support",
        ),
        "assign.load": _t(
            "Assign → Joint → Loads",
            "Assign — joints",
            "Nodal forces and moments, applied in a load pattern.",
            """
# Values
- **Fx, Fy, Fz** — forces; **Mx, My, Mz** — moments, in project units.
- **Pattern** — which load pattern the load belongs to; a new one creates a
  default linear time series with it.
- Sign convention: global axes. Gravity is a negative Fz in a Z-up model.

# Mechanics
A nodal load is applied at a node; it does not depend on the members touching
it. A load on a node with no stiffness in that direction (an unrestrained node
that only touches trusses, say) produces a singular system rather than a large
displacement, so the solver's refusal is a modelling message, not a failure of
the solver.
""",
            "define.plain_pattern",
            "assign.distributed_load",
        ),
        "assign.zero_length_section": _t(
            "Assign → Joint → Zero-Length Section",
            "Assign — joints",
            "A full section acting between two coincident nodes.",
            """
A `ZeroLengthSection` element puts a **section** (elastic, fibre or aggregated)
between two nodes at the same point. It is how a plastic hinge, a base
connection or a section-level spring is modelled: the element's deformation is
the relative displacement and rotation of the two nodes.

# Values
- **Section** — what the element is made of, as a section rather than a set of
  materials.
- The two nodes must be **coincident**; they are a deliberate pair, and Edit →
  Check Model for Duplicates leaves them alone on purpose.
- The local axes come from the element's orientation: in a 3D model the two
  coincident nodes give no direction, so the orientation is taken from the global
  axes (Y for the section's local x).
""",
            "assign.bearing",
            "mechanics.fiber_sections",
        ),
        "assign.link": _t(
            "Assign → Joint → Link",
            "Assign — joints",
            "A twoNodeLink or a Triple Friction Pendulum between two selected joints.",
            """
# twoNodeLink
One uniaxial material in each local direction you tick: 1 axial (local x),
2 and 3 shear, 4 to 6 rotations (2D: axial, shear, rotation). Use it for a
viscous damper (`ViscousDamper`), a gap or hook (`ElasticPPGap`), a hinge spring
(`ModIMKPeakOriented`), an isolator made of any hysteretic material, or a panel
spring. The local axes are OpenSees' (x from i to j); coincident joints need an
**orientation** "x1 x2 x3 y1 y2 y3" (the dialog proposes x vertical, y along X).
Optional element mass and stiffness-proportional Rayleigh damping.

# Triple Friction Pendulum (3D)
Three friction models (surfaces 1 to 3, the two inner surfaces share the first),
a vertical material and three rotational ones, the effective radii L1 to L3 and
the displacement limits d1 to d3, the axial load W used for the initial friction,
the yield displacement uy, the tension stiffness kvt, the minimum vertical force
and the tolerance. Apply the gravity load in a case of its own, in steps, and use
it as the **preload** of the dynamic case: the pendulum needs its axial load
before it can slide (as OpenSees' own examples do).

ElastomericX, LeadRubberX and HDR are not offered yet: with realistic inputs their
vertical response in OpenSees 3.8 could not be validated; use the elastomeric
bearings of Assign → Joint → Bearing.
""",
            "assign.bearing",
            "define.friction_library",
        ),
        "assign.bearing": _t(
            "Assign → Joint → Bearing (isolator)",
            "Assign — joints",
            "An elastomeric or sliding isolator between two coincident nodes.",
            """
# Values — elastomeric (plasticity / Bouc-Wen)
- **Kinit** — initial shear stiffness.
- **Qd** — characteristic strength (the loop's flat part).
- **alpha1, alpha2** — post-yield stiffness ratios; **mu, eta, beta, gamma** for
  the Bouc-Wen shape.

# Values — sliding (flat slider, single friction pendulum)
- **Friction model** — a named model from Define → Friction Models, plus its
  coefficient.
- **R_eff** — the pendulum radius (single FP), which sets the isolated period
  T = 2π√(R_eff/g).
- **Kinit** — the initial stiffness before sliding.

# Modelling notes
- The two nodes must be **coincident**: the isolator *is* the relative movement
  between them, and one of them is normally restrained to the ground.
- A bearing in 2D and 3D differ in which DOF are mobilised; a 3D bearing
  restrains the vertical and the two rotations it does not slide in.
- The property dock shows the derived yield displacement and force, and the
  isolated period, so the numbers can be sanity-checked before running.
""",
            "define.friction_library",
            "mechanics.isolators",
        ),
        # ──────────────────────────── Assign: frame ────────────────────────────
        "assign.section": _t(
            "Assign → Frame → Section",
            "Assign — frame",
            "Give the selected frame members a section.",
            """
Point the selected `ElasticBeamColumn`, `ForceBeamColumn`, `DispBeamColumn` or
`BeamWithHinges` elements at a section from the library.

- An **elastic** section carries E and the geometric properties; a **fibre**
  section carries materials and needs a non-linear case.
- A `BeamWithHinges` additionally needs a hinge section at each end, which the
  Assign → Frame → Hinge command sets.
- A plate section cannot be assigned to a frame member: it has a thickness, not
  a bending stiffness.
""",
            "define.section_library",
            "assign.material",
        ),
        "assign.material": _t(
            "Assign → Frame → Material",
            "Assign — frame",
            "Give the selected truss or zero-length elements a material.",
            """
Trusses and zero-length elements point at **materials**, not sections: a truss
has an area and a uniaxial material; a zero-length element has one material per
DOF or a list of them.

- Assigning a material to a beam-column does nothing: its stiffness comes from
  its section (which in turn points at materials if it is a fibre section).
- The element's own parameters (the truss area, the zero-length DOF list) are
  set when the element is created or in the property dock.
""",
            "define.material_library",
            "assign.section",
        ),
        "assign.geom_transf": _t(
            "Assign → Frame → Geometric Transformation",
            "Assign — frame",
            "How an element's local axes relate to the global ones, and how large displacements are handled.",
            """
# Values
- **Linear** — small displacements; the stiffness matrix is built once. Correct
  for most linear work and the default.
- **PDelta** — includes the second-order effect of axial force on bending: a
  compressed column loses lateral stiffness. This is what a stability or
  second-order analysis needs.
- **Corotational** — large displacements and rotations: the element's rigid-body
  motion is removed and the deformation is measured in a frame that follows it.
  Needed for a cable, a snap-through, or a member that rotates appreciably.

# Mechanics
With *P-Delta*, the geometric stiffness subtracts from the material stiffness in
proportion to the axial force. The **critical load** is where the two cancel; a
model that becomes singular as the load rises is telling you it has reached it.
The transformation also defines the local axes: for a member whose axis is
vertical, the local x/y orientation comes from the transformation, and the sign
of a diagram follows from it.
""",
            "assign.integration",
            "mechanics.static",
        ),
        "assign.integration": _t(
            "Assign → Frame → Beam Integration",
            "Assign — frame",
            "How many points along a member the section response is sampled at.",
            """
# Values
- **Rule** — `Lobatto` (points at the ends and inside), `Legendre`, `NewtonCotes`,
  `Radau`, `Trapezoidal`, `Simpson`, or `HingeRadau` variants for
  `BeamWithHinges`.
- **Points** — how many integration points. Three to five is typical; a
  force-based member with a fibre section needs enough points to follow the
  curvature (often 5 to 7 for a member that yields).

# Mechanics
The member's flexibility is integrated from the *section* response at those
points: a fibre section that yields at mid-span but is only sampled at the ends
is not seen to yield. More points is more accurate and more expensive — the cost
is a section evaluation per point per iteration, per element.
""",
            "mechanics.fiber_sections",
            "assign.geom_transf",
        ),
        "assign.distributed_load": _t(
            "Assign → Frame → Distributed Load",
            "Assign — frame",
            "A uniform load along a member, in the element's local axes.",
            """
# Values
- **wy, wz** — the transverse load per unit length in the element's **local**
  y and z axes; **wx** — the axial load per unit length.
- **Pattern** — which load pattern it belongs to.
- Sign convention: gravity on a horizontal member is usually `wy = -q`, because
  the local y is transverse. The local axes come from the geometric
  transformation and the member's orientation, so the same physical load can be
  a different component on members running in different directions.
- The command asks for one load per member; for several, repeat it.

# Mechanics
The load is applied as equivalent nodal forces and moments by OpenSees for a
linear transformation. The diagram it produces is the member's own bending
moment, which is what Display → Force Diagram draws.
""",
            "define.plain_pattern",
            "display.force_diagram",
            "assign.frame_point_load",
        ),
        "assign.frame_point_load": _t(
            "Assign → Frame → Point Load",
            "Assign — frame",
            "A concentrated force inside a member, in the element's local axes.",
            """
# Values
- **Px, Py, Pz** — the force along the element's **local** x (axial), y and z
  axes. As for a distributed load, gravity on a horizontal member is usually a
  negative Py.
- **Distance from end i** — where the load acts, either **relative** (a
  fraction of the length, 0 at node i, 1 at node j) or **absolute** (a length).
  An absolute distance becomes a different fraction on members of different
  length; a member shorter than the distance is skipped and named in the log.
- Only frame (beam-column) elements take it: trusses, zero-length elements,
  bearings and faces in the selection are skipped.

# Mechanics
It is emitted as `eleLoad -beamPoint`. An elastic beam-column takes the exact
fixed-end forces; a force- or displacement-based element resolves the load
through its integration points, so the end forces are approximate unless the
member is split at the load (Edit → Mesh keeps the load on the piece it falls
on). A force-based element only takes an element load into its forces after
a solve, so the runner follows each static step that loads one with a second
solve at the same load; any algorithm and test then gives the converged answer,
except a test relative to the first iteration (RelativeNormDispIncr), which is
refused for more than one step.
""",
            "assign.distributed_load",
            "define.plain_pattern",
        ),
        "assign.frame_releases": _t(
            "Assign → Frame → Releases/Partial Fixity",
            "Assign — frame",
            "Pin a member end about a local axis, or make it partially fixed.",
            """
# Values
- **Torsion (T), M2, M3** at **end i** and **end j** — a released action carries
  no force at that end. M3 is the moment about local 3 (local z), the in-plane
  moment of a 2D frame; M2 the moment about local 2 (local y). A 2D frame
  releases M3 only.
- **Spring** — a partial-fixity stiffness (moment per radian) on a released
  action; 0 is a full release. The end then carries `k × relative rotation`.
- Torsion released at both ends leaves the member free to spin about its own
  axis and is refused unless one end has a spring.
- A joint where every member releases the same rotation and nothing restrains
  it is unstable: the run stops and names the joint and DOF.

# Mechanics
OpenSees has no release option on force- or displacement-based elements, and
the 3D elastic element's `-releasez/-releasey` gets the end moments of a
`-beamPoint` load wrong, so the member end is connected to a hidden node at the
joint instead: `equalDOF` ties the translations and every kept rotation, a
`zeroLength` element along the member's axes carries the springs. A member whose
local axes are skewed to the global axes and that keeps torsion while releasing
both moments gets a penalty spring 10^8 times its own rotational stiffness for
the torsion (an elastic member only; a fibre member is asked to release torsion
too). The hidden nodes' reactions are added to the joint's.

A release at an end that also has an end offset or an insertion point acts at
the face of the rigid zone, as in SAP2000: the hidden node hangs off the joint
with `rigidLink beam`, and such a model runs with the Transformation constraint
handler even if the case asks for Plain (Plain ignores a rigid link).

At a joint that a rigid diaphragm, an equalDOF or a rigid link constrains, a
hidden node tied by `equalDOF` would chain through that constraint, which
OpenSees solves wrong without an error; there the release is made inside the
element or with penalty springs instead (see Assign → Joint → Diaphragm).
""",
            "assign.end_offsets",
            "assign.insertion_point",
            "assign.diaphragm",
        ),
        "assign.end_offsets": _t(
            "Assign → Frame → End (Length) Offsets",
            "Assign — frame",
            "Rigid end zones at the joints, e.g. the part of a beam inside a column.",
            """
# Values
- **End-I / End-J length** — the offset measured along the member from each
  joint, typically half the depth of the member it frames into.
- **Rigid-zone factor** — the part of each offset that is rigid (0 to 1). The
  flexible length is `L - factor × (length i + length j)`.
- **Automatic from connectivity** — instead of typed lengths, each end takes the
  largest half-extent, measured along this member, of the section of the other
  frame members that meet it at that joint (SAP2000 "automatic from
  connectivity"): a 0.4 m column gives a beam 0.2 m at that end. Members parallel
  to it and members whose section size is unknown add nothing. The lengths are
  worked out once, when you press OK, and stored like typed ones (change the
  geometry and assign again).

# Mechanics
The rigid zones are `geomTransf ... -jntOffset`, so they add no DOF. The end
forces, and the force diagrams, are those of the flexible part, at the faces of
the rigid zones. Loads are still given along the whole joint-to-joint length:
the part on a rigid zone goes straight to its joint as a force and the moment of
that force about the joint. A 3D Corotational transformation ignores joint
offsets in OpenSees 3.8, so the combination is refused.
""",
            "assign.insertion_point",
            "assign.frame_releases",
        ),
        "assign.insertion_point": _t(
            "Assign → Frame → Insertion Point",
            "Assign — frame",
            "Which point of the cross section sits on the line between the joints.",
            """
# Values
- **Cardinal point** 1-11, as in SAP2000: 1-3 bottom left/center/right, 4-6
  middle, 7-9 top, 10 centroid, 11 shear center (taken at the centroid). Bottom
  and top are -/+ local 2 (local y), left and right -/+ local 3 (local z),
  looking from end i towards end j. Point 8 puts the top of a 2D beam at the
  joints.
- **Offset along 2 / 3** — a further offset of the member at both ends; a 2D
  frame cannot be offset along 3 (out of its plane).
- The section size comes from an elastic section's shape (or the rectangle with
  its A, Iz and Iy) or a fibre section's patches.

# Mechanics
Realised with the same rigid joint offsets as end offsets: the member's flexible
length is unchanged, and an axial force along the offset axis bends it.
""",
            "assign.end_offsets",
        ),
        "assign.property_modifiers": _t(
            "Assign → Frame → Property Modifiers",
            "Assign — frame",
            "Multipliers on a member's section properties, e.g. 0.35 Ig for cracked beams.",
            """
# Values
- **Area, Torsional constant, I22, I33** — multiply A, J, Iy and Iz of the
  member's elastic section (or the elastic interior of a BeamWithHinges). The
  run builds a derived elastic section for every distinct combination.
- **Shear areas 2 / 3** — multiply the section's shear areas As2 / As3, so they
  change a result only when the elastic section defines them (the member is then
  an `ElasticTimoshenkoBeam`, see Define → Section Library). On a section
  without shear areas the member is Euler-Bernoulli and they have no effect.
- **Mass** — scales an elastic beam-column's mass per length.
- **Weight** — scales the member's self weight.
- A fibre section has no property to scale: stiffness modifiers other than 1 on
  a fibre member stop the run with a message.
""",
            "assign.frame_releases",
        ),
        "assign.temperature_load": _t(
            "Assign → Frame → Temperature Load",
            "Assign — frame",
            "A temperature change of the selected members: uniform, and across each axis.",
            """
The member's temperature changes by `ΔT + g_y·y + g_z·z` at the point `(y, z)` of
its cross section, in the member's local axes:

- **α** — the coefficient of thermal expansion, about 1.2e-5 per °C for steel and
  for concrete;
- **Uniform ΔT** — heats (positive) or cools the whole section: a free member grows
  `α ΔT L`, a member held at both ends takes a compression `EA α ΔT`;
- **Gradient along local y / z** — the temperature difference per unit depth,
  `(T on the + face - T on the - face) / depth`. A free member bends to a
  curvature `α g` toward the cooler face; a member held at both ends takes a
  constant moment `EI α g`. Which axis is "up": a horizontal member's local
  **y** points up in a **2D** model, its local **z** in a **3D** one (local y is
  then horizontal), so a hot top face is a positive `gradient_y` in 2D and a
  positive `gradient_z` in 3D.

# How it is solved
OpenSees' elastic frame elements take no thermal load, so the member is held
fixed, its fixed-end forces are applied to the structure with the opposite sign,
and the fixed-end forces are added back to the member's end forces. The
displacements, reactions, force diagrams, combinations and the steel check then
see the real member forces: `N = EA (ε - α ΔT)`, `M = EI (κ - α g)`.

# Limits
- Elastic beam-columns with an elastic section (property modifiers on A and the
  inertias apply), **without end releases, end offsets or an insertion point**:
  the action refuses other members before changing anything.
- **Static cases only**, under LoadControl with a Linear or Constant time series
  (a case with N steps applies it in N parts). Other case types refuse a pattern
  that carries temperature loads.
- The load goes into the active Plain pattern (a default one is created if there
  is none); Edit → Mesh and Replicate carry it to the new members.
""",
            "assign.distributed_load",
            "analyze.cases",
        ),
        "assign.trapezoidal_load": _t(
            "Assign → Frame → Trapezoidal Load",
            "Assign — frame",
            "A load varying linearly over part or all of a member.",
            """
# Values
- **wx, wy, wz** at the **start** and the **end** — load per unit length in the
  element's local axes, varying linearly in between.
- **x/L start / end** — where the load starts and ends, as fractions of the
  joint-to-joint length from end i. Equal start and end values give a partial
  uniform load.

# Mechanics
On an elastic or displacement-based element each linear piece is emitted as
three `-beamPoint` loads at its Gauss points, which give exactly the fixed-end
forces of the linear load (OpenSees 3.8's 3D elastic element ignores the end
values of a native trapezoidal load, and `dispBeamColumn` drops it with a
warning). A force-based element takes the native
`-beamUniform wa ... aL bL wb ...`, integrated at its integration points (exact
for a full-length load on an elastic section). A part on a rigid end zone goes
to the joint.
""",
            "assign.distributed_load",
            "assign.end_offsets",
        ),
        "assign.surface_load": _t(
            "Assign → Area → Surface Load on Shells",
            "Assign — areas",
            "A uniform pressure on the selected shells, as consistent nodal forces.",
            """
Puts a uniform load per area on every selected shell (`ShellMITC4`), in the load
pattern you pick. The solver receives it as consistent nodal forces: each corner
takes the value times the integral of its shape function over the shell, so the
four add up to value × area also on a warped quad. Beams and other elements in
the selection are skipped. A shell that is meshed later passes the load to every
piece, and Edit → Replicate copies it with the shell.

# Values
- **Value** — force per area, signed along the direction.
- **Direction** — **Global Z** (a floor's weight is a negative value), **Global
  X / Y**, or the **shell normal** (local 3: the right-hand turn of its nodes
  1-2-3-4, so a pressure on a wall or a sloped roof).
""",
            "assign.floor_load",
            "define.create_shell",
        ),
        "assign.floor_load": _t(
            "Assign → Area → Floor Load to Frames",
            "Assign — areas",
            "A floor load handed to the beams around each bay, one-way or two-way.",
            """
For a floor modelled with beams only (no shells): select the floor's joints and
the load goes to **every rectangular bay** whose four corners are selected and
whose four sides are framed by beams. A beam meshed into pieces still counts as
one side; a joint in the middle of a beam is not a corner. The load acts
downward (-Z) and reaches the beams as trapezoidal loads in their own local
axes, drawn on the canvas like any other member load.

# Values
- **Load** — force per area, downward.
- **Distribution**
  - **Two-way** — 45° yield lines from the corners: an edge of length L takes
    q min(t, L - t, s/2) along its length (s the bay's short side), a trapezoid on
    a long edge and a triangle on a short one. The four edges carry q × area.
  - **One-way, spanning along X / Y** — the slab spans in that direction, so the
    two beams across the span each take q × span / 2, uniform.

# Limits
A bay must be horizontal, rectangular and axis-aligned to be found from a
selection; a sloped or irregular area is loaded with shells and a surface load.
A 3D model only (a 2D frame takes its beam loads directly).
""",
            "assign.surface_load",
            "assign.trapezoidal_load",
        ),
        "assign.imposed_displacement": _t(
            "Assign → Joint → Imposed Displacement",
            "Assign — joints",
            "A static displacement of the selected joints: a support settlement.",
            """
Imposes a displacement on one DOF of each selected joint, in the load pattern you
pick (OpenSees `sp` in that pattern). On a **restrained** DOF the support moves by
that much — a settlement, the classic case. On a **free** DOF the joint is held
at that value for the cases that run the pattern, as if a support were there.

The application removes the support's own constraint before imposing the new
value, and runs such a case with the **Transformation** constraint handler even
when it is set to Plain: Plain silently ignores a nonzero imposed value.

# Values
- **DOF** — the model's own DOFs: Ux, Uy, Uz, Rx, Ry, Rz in 3D; Ux, Uz, Ry in a
  2D frame (the X-Z plane).
- **Value** — length (or radians for a rotation), in the global sign convention:
  a settlement is negative Uz.

Check: a two-span continuous beam whose middle support settles d has the middle
reaction 6 E I d / L³ — the application matches it.
""",
            "assign.support",
            "assign.load",
        ),
        "assign.wall": _t(
            "Assign → Frame → RC Wall (MVLEM)",
            "Assign — frame",
            "Turn the selected vertical members of a 2D model into reinforced concrete wall segments.",
            """
Replaces each selected **vertical** two-joint member with an OpenSees `MVLEM`
segment (Multiple-Vertical-Line-Element Model, Orakcal, Wallace and Conte):
vertical fibres across the wall length — concrete plus the steel at its ratio —
couple axial load and flexure, and one horizontal shear spring at height `c h`
carries the shear. Ids and joints are kept (bottom joint first); members that
are not vertical are left as they are. 2D models only.

# The section
- **Wall length L** and **thickness t**, split into **vertical fibres** of equal
  width; with a **boundary element length** > 0 each end is a boundary element
  with its own **steel ratio** (and fibres of about the web's width).
- **Concrete** and **steel** uniaxial materials (for example `Concrete02` and
  `Steel02`, or those of the Concrete Section Wizard).
- **Shear**: elastic with a shear modulus G (it starts at the concrete's initial
  modulus over 2.4) — one material per segment height is created with stiffness
  `G L t / h`, since the spring is a force-displacement spring of its own segment
  — or an existing uniaxial material for every segment (a nonlinear shear law).
- **Centre of rotation c** (0.4 is the usual value) and the **density** for
  the segment's mass.

# Modelling notes
- The rotation of a segment is lumped at `c h`: use **several segments per
  storey** (draw the wall's members split, or Edit → Divide Frames), and the
  curvature converges to the continuous one — 40 segments give the elastic
  cantilever's `P H³ / 3EI + P H / GA` to 1 %.
- Floors frame into the wall's joints; the wall has no width in the drawing.
- Shear and flexure are not coupled in `MVLEM`. gidopensees' `FiberInt` section
  (shear-flexure interaction) is not available in OpenSeesPy 3.8.
""",
            "assign.hinge",
            "define.concrete_section",
            "define.material_library",
        ),
        "assign.hinge": _t(
            "Assign → Frame → Hinge",
            "Assign — frame",
            "The hinge sections of a BeamWithHinges member.",
            """
A `BeamWithHinges` element concentrates the inelastic behaviour in a **hinge
length** at each end, with an elastic interior. It is the efficient way to model
a member that yields at its ends — a beam in a moment frame, a column base.

# Values
- **Hinge length at i and j** — how long the inelastic zone is. A common choice
  is a fraction of the section depth (0.5h to 1h).
- **Hinge sections** — the fibre (or elastic) section used inside the hinge
  zone, one per end; the interior uses the member's own section.

# Mechanics
The hinge length decides how much rotation the member can take before the
section's ultimate curvature is reached: a longer hinge spreads the same
curvature over more length. It is a modelling choice with a real effect on
ductility, not a numerical detail.
""",
            "mechanics.fiber_sections",
            "assign.section",
        ),
    }
)

TOPICS.update(
    {
        # ──────────────────────────── Analyze ────────────────────────────
        "analyze.cases": _t(
            "Analyze → Cases",
            "Analyze",
            "Define the analyses: type, steps, solver options.",
            """
A case is what to solve. Several cases coexist on one model — a gravity static
case, a modal case and a pushover, for instance — each with its own settings.

# The six types
- **Static** — equilibrium under the patterns' loads, in N steps. See
  **Static analysis**.
- **Modal** — eigenvalues and mode shapes; needs mass. See **Modal analysis**.
- **Pushover** — displacement-controlled monotonic push to a target. See
  **Pushover**.
- **Transient** — time integration of a ground motion or a time series. See
  **Transient analysis**.
- **Response spectrum** — modal maxima combined by SRSS or CQC. See
  **Response spectrum**.
- **Influence line** — a unit load walked along a chain of members, one linear
  solve per stop, with an optional vehicle. See **Display → Influence Line**.

# Options that apply to most types
- **Steps** and, for a transient, **dt**.
- **Numberer, system, algorithm, convergence test** — see Numberer, system and
  solver. The defaults are chosen to work; change them for size or for a case
  that struggles. Every option of OpenSeesPy 3.8 that runs is offered:
  - systems BandGeneral, BandSPD, ProfileSPD, SparseGeneral, SparseSYM, UmfPack,
    FullGeneral;
  - algorithms Linear, Newton, NewtonLineSearch, ModifiedNewton, KrylovNewton,
    SecantNewton, RaphsonNewton, PeriodicNewton, BFGS, Broyden;
  - tests NormDispIncr, NormUnbalance, EnergyIncr, the Relative… ones (relative to
    the first iteration; on macOS, BFGS and Broyden do not meet the relative
    displacement and energy tests in OpenSees 3.8: pair them with NormDispIncr),
    NormDispAndUnbalance and NormDispOrUnbalance (the tolerance is used for both
    norms) and FixedNumIter (exactly the max iterations; do not pair it with
    SecantNewton, which divides by zero once converged);
  - static integrators LoadControl, DisplacementControl, ArcLength,
    MinUnbalDispNorm; transient Newmark (γ, β), HHT (α), GeneralizedAlpha (αM, αF),
    CentralDifference and TRBDF2 (no parameters). The parameter rows follow the
    integrator. Diagonal and ExplicitDifference are not offered: they need mass on
    every DOF.
- **Patterns** — which load patterns take part, and in what order.
- **Recorders** — what to save (node displacements, reactions, element forces).
  Asking for less is faster and produces smaller result files.

# Chained workflows
A gravity preload followed by `loadConst -time 0.0` and then a pushover or a
transient is the standard way to start a non-linear case from the deformed
gravity state. The case list applies the patterns in the order given.
""",
            "mechanics.static",
            "analyze.run",
            "display.influence_line",
        ),
        "analyze.stability": _t(
            "Analyze → Check Model Stability",
            "Analyze",
            "Find the mechanisms of the model before running anything.",
            """
Builds the model exactly as an analysis would, captures its initial stiffness
matrix once and looks for **mechanisms**: motions of the free joints that no
member, spring or support resists. A clearly stable model has none; a model
with a mechanism cannot be solved, or solves into nonsense.

The check runs in the same child process as an analysis, so a model OpenSees
cannot even build does not take the window with it.

# What it reports
- **Free DOFs that no element stiffens** — a joint DOF that nothing connects
  to: a rotation of a truss joint in a frame model, a joint whose every member
  releases the same moment, a node on its own.
- **Mechanisms** — each one lists the joints and DOFs that move the most in it,
  with their share of the motion (+1.00 is the largest). A frame without
  bracing or base fixity sways; a beam on two rollers slides; a chain of hinges
  folds. In a 2D model the DOFs are Ux, Uz and Ry (the X-Z plane).
- **Negative stiffness** and **ill-conditioning** are reported separately from a
  mechanism. A small positive stiffness is not silently called a mechanism.
- **Ungrounded components** �?" a connected group with no restraint or grounded
  spring �?" are checked with a rigid-body translation. When the motion costs no
  stiffness it is reported as a mechanism, with a partial result because the
  rest of the model is not searched.
- **Incomplete** checks say so: an unavailable sparse backend, a non-converged
  eigenvalue search or a lower-bound mechanism count is not presented as a
  stable model.

The joints that move are selected in the view, so you can see where to add a
support, a brace or a member, or which DOF to restrain.

# How it decides
The matrix is captured through OpenSees' **PythonSparse** system as CSR when
the engine provides it, without a dense `n × n` array for a large model. A
small model (up to 1 200 equations) uses a dense symmetric eigenvalue reference;
larger models use a sparse shifted eigenvalue search near zero after a diagonal
scaling. A zero is reported below 1e-10 of the matrix scale, with a normalized
eigenpair residual check. Constraints (equalDOF, rigid links, diaphragms) are
applied first, so a DOF a constraint ties is not counted twice. Mechanism
vectors are expanded to the constrained nodes for the report and selection.
The CSR pointer's last entry defines the stored entries; if OpenSees reports a
larger allocated `nnz`, the stored prefix is used and the difference is noted.
Integer CSR buffers are accepted in 32-bit or 64-bit form.
The check reads the **initial** stiffness: a model that only becomes unstable as
it yields or buckles needs a nonlinear analysis; this is not a buckling factor.

The child reports phases (precheck, build, capture, diagnose, reconstruct) to
the console. **Analyze → Cancel Stability Check** stops it, and the GUI also
imposes a soft 300 s limit; a long native eigenvalue call cannot be interrupted
cooperatively, so the parent terminates the child at its hard deadline. For
reproducible families use `python tools/stability_bench.py --family frame
--size 12` (or `--family truss --mechanism`).
""",
            "analyze.run",
            "assign.support",
        ),
        "analyze.check_model": _t(
            "Analyze → Check Model",
            "Analyze",
            "Find loose nodes, unconnected elements and static instability before running.",
            """
OpenSees does not explain a model it cannot solve: a node nobody connects to, a
member that points at a deleted node or a frame missing one support all end as a
singular stiffness matrix, a warning the solver prints and moves past, and
displacements that are really the load vector. **Check Model** finds these
*before* the run, names the nodes and elements involved and says what to look at.
It never changes the model. **Run** performs the same check on its way in.

# What it finds
- **Loose nodes** — a node no element and no constraint touches. Free, it is an
  *error*; fully restrained, only a *warning* (it does nothing).
- **Broken members** — an element that refers to a node that no longer exists,
  lists the same node twice, or has zero length (two nodes at the same point). A
  zero-length element or bearing whose nodes are *apart* is a warning.
- **Separate parts** — a part with no support is a rigid body (*error*). Several
  supported parts are a *warning*; when two nodes of different parts sit at the
  same point the message names them, because that is nearly always a node that
  was never merged (see Edit → Check Model for Duplicates).
- **Mechanisms** — groups of nodes that can move *without deforming any element*:
  a square of bars with no diagonal, two bars in a line, a beam pinned at one end,
  a truss modelled with free rotations. Each is reported with the nodes and the
  DOF (Ux, Uy, Rz …) that are free to move, and how many independent motions there
  are.

# How stability is decided
Each element is replaced by its independent deformation modes with unit stiffness
(a bar has one, a 3D frame six, a shell eighteen) and the stiffness matrix is
assembled over the DOF that are not restrained. A zero eigenvalue is a mechanism.
Because nothing about E, A or I enters, the answer does not depend on units or on
how stiff one member is next to another, and it does not run OpenSees.

# What it cannot see
It is a **linear, small-displacement** test of the *connectivity*:

- A structure that is stable only through its deformation (a cable) or through a
  gap, a slider or a hinge that locks, is outside it.
- Geometry that is *almost* degenerate (bars a hair out of line) passes; the
  solver will then give large displacements instead of failing.
- A model with more than 3000 free DOF in one connected part is skipped with an
  information line (set `OPENSEES_STUDIO_STABILITY_MAX_DOF` to raise the limit).

# Run anyway
If the check finds errors, Run stops at the list and offers **Run anyway**. A
modal analysis of a free-floating structure is a legitimate reason to; the
default button is Cancel. Warnings do not interrupt: they are written to the
console.
""",
            "edit.check_duplicates",
            "analyze.run",
            "assign.support",
        ),
        "analyze.run": _t(
            "Analyze → Run",
            "Analyze",
            "Run the selected cases in a separate process and collect the results.",
            """
The solve happens in a **child process** (`python -m opensees_studio.run`, or
the bundle re-entering itself), not in the interface:

- the GUI stays responsive, and a case can be cancelled;
- a solver crash cannot take the model with it — the child's exit code and its
  last error are reported;
- the child speaks one JSON object per line, so progress and log lines stream
  back while it runs.

Before starting, a **pre-run snapshot** of the project is written next to the
file (or into the app data directory for a never-saved project): that is the
crash-recovery path, and it is removed on a normal save or close.

Results go to an HDF5 file plus a manifest, losslessly, and are what the Display
commands read. An early stop (a transient that stops converging) is a *result*:
the log records the step reached and the results keep what was computed.
""",
            "analyze.cases",
            "analyze.check_model",
            "display.deformed",
            "analyze.results_database",
        ),
        "analyze.run_all": _t(
            "Analyze → Run All Cases",
            "Analyze",
            "Run every analysis case of the model, one after another, in one child process.",
            """
The batch door: every case defined in Analyze → Cases runs in a single child
process, in the order they are listed, and each one lands in the results
database as its own run. Progress and log lines stream back as they do for a
single run.

Use it before a report, or after changing something that invalidates every case
(a section, a material, the mass source). To run only some of them, use
**Run Selected Cases**.
""",
            "analyze.run",
            "analyze.run_selected",
            "analyze.results_database",
        ),
        "analyze.run_selected": _t(
            "Analyze → Run Selected Cases",
            "Analyze",
            "Tick the cases to run and run them together in one child process.",
            """
Every case is listed with a checkbox, all ticked by default. Untick what you do
not need and press OK; the ticked cases run in one child process, in list order,
and each one is recorded in the results database as its own run.

This is the middle ground between **Run** (one case, with its damping overrides
and the log in front of you) and **Run All Cases** (everything).
""",
            "analyze.run",
            "analyze.run_all",
            "analyze.results_database",
        ),
        "analyze.clear_results": _t(
            "Analyze → Delete All Results",
            "Analyze",
            "Forget every stored result: the session's and the project's database.",
            """
Removes the results of this session from memory (what Display can show and what
the reports use) and deletes the project's `<project>_results.sqlite` file. The
model, its analysis cases and its load combinations are untouched, so the next
run starts from a clean slate.

It asks first: there is no undo. A different project's database is never
touched, because the file lives beside its own model.

To replace one case's numbers, just run it again — a case keeps one run, which
is overwritten (see *Analysis results database*).
""",
            "analyze.results_database",
            "analyze.run",
        ),
        "analyze.results_database": _t(
            "Analysis results database",
            "Analyze",
            "Every run is appended to a SQLite file with all node and element results, for later queries.",
            """
Each finished case is written to **`<project>_results.sqlite`**, next to the
project file (a never-saved project writes to the app data directory as
`untitled_results.sqlite`). SQLite is used because a static case on a 500-joint
model writes thousands of rows and a time history writes far more: one file,
indexed, readable by a notebook, a spreadsheet or the `sqlite3` CLI, and safe to
interrupt.

There is **one run per case**: re-running a case replaces its previous rows, so
the file always reflects the latest run of each case. Different cases coexist;
**Analyze → Delete All Results** removes both the session's results and the
file.

| Table | One row per |
|---|---|
| `runs` | run: case id and name, kind, timestamp, step count, `dt`, HDF5 path |
| `node_disp` / `node_reaction` | node × step: `ux, uy, uz, rx, ry, rz` |
| `element_forces` | element × step: `c1 … c12` (local forces) |
| `element_stresses` | element × step: shell resultants `n11 … v23` |
| `storey_shear`, `section_cut_forces` | storey / cut × step |
| `modal`, `mode_shapes` | mode, and mode × node |

Load combinations are stored as two runs (`combination:max`, `combination:min`);
a response spectrum is one pseudo-step of peak values; a transient run records
the HDF5 path and indexes its node displacement history (velocity, acceleration
and element state stay in the lossless HDF5 file).

Query it without the application:

```sql
SELECT r.case_name, d.node_id, d.step, d.ux
FROM node_disp d JOIN runs r USING (run_id)
WHERE r.run_id = 3 AND d.node_id = 12 ORDER BY d.step;
```

If the file cannot be written, the run still succeeds and the console says so:
results are never lost because the database failed.
""",
            "analyze.run",
            "analyze.run_all",
            "display.select_results",
        ),
        # ──────────────────────────── Display ────────────────────────────
        "display.select_results": _t(
            "Display → Show Results Of",
            "Display",
            "Pick which stored case or load combination the Display views show.",
            """
The Display views (deformed shape, force diagram, shell contours) and the results
panel show one result at a time — normally the latest run. Show Results Of lists
every case result that is still current for the model, and every load
combination, and switches to the one you pick without running anything.

- A combination is combined from the current case results. When one of its cases
  has none (never run, or the model changed since), run the combination from
  Analyze → Run: it runs only the missing cases.
- A combination with a maximum and a minimum draws both force diagrams at once,
  offers a Max/Min choice in the deformed shape, and lists both in the tables;
  Export CSV writes the table shown.
""",
            "define.load_combinations",
            "display.deformed",
            "display.force_diagram",
        ),
        "display.deformed": _t(
            "Display → Deformed Shape",
            "Display",
            "The structure displaced by the results, with a scale slider.",
            """
Draws the model in its deformed configuration from a static, pushover or
transient case. The scale slider exists because real displacements are usually
invisible next to the structure's size.

- The automatic scale takes a fraction of the model's size, so the shape is
  visible without reading numbers.
- The deformed shape is what actually happened; a shape that looks wrong (a member
  straightening, a joint separating) is usually a modelling error, not a plotting
  one.
- Display → Back to Model returns to the undeformed view.
""",
            "display.mode_shape",
            "display.back_to_model",
        ),
        "display.mode_shape": _t(
            "Display → Mode Shapes",
            "Display",
            "Animate the modes of a modal case.",
            """
One mode at a time, animated, with the period and the modal participation
reported so the mode can be identified.

- Mode 1 is not always the one you expect: a torsional mode can come first in an
  irregular plan, and the participation factors are how you see it.
- The signs of a mode shape are arbitrary; the application normalises them so two
  runs look the same.
- A repeated eigenvalue (a symmetric structure) gives any two orthogonal shapes
  of that subspace; the application orthogonalises them before display.
""",
            "mechanics.modal",
            "display.deformed",
        ),
        "display.reactions": _t(
            "Display → Show Reactions",
            "Display",
            "The support reactions of the case on screen, as arrows and arcs.",
            """
Draws, at every restrained node, a red arrow for the reaction force and a
violet circle for the reaction moment, both **proportional to their
magnitude**: the largest force and the largest moment of the case set the
length and the radius, so the picture compares nodes with each other rather than
with an absolute value.

# Reading it
- The arrow points along the reaction: the force the support applies to the
  structure. An arrow that ends on the joint is a force pulling that way.
- The circle lies in the plane perpendicular to the moment, and you read its
  turning sense with the right hand: thumb along the moment, fingers curling the
  way it acts.
- The case shown is the one in the caption (top left). Change case and the
  overlay follows.
- The numbers of the same case are in the **Reactions** tab and in
  *Display → Reactions Table*.

Nothing is drawn when the case reports no reactions (a free-floating model, or
element types that do not deliver them).
""",
            "display.reactions_table",
            "analyze.results_database",
        ),
        "display.reactions_table": _t(
            "Display → Reactions Table",
            "Display",
            "The reactions of the case being shown, one row per restrained node.",
            """
Brings the **Reactions** tab of the bottom dock to the front: node, Fx, Fy, Fz,
Mx, My and Mz in global components, in project units. It follows the case on
screen, so it updates when the displayed result changes.

# Reading it
- Only nodes that report a reaction appear; a free joint is not listed as a row
  of zeros.
- A case with a time axis shows the **final step**, the same one the arrows draw.
- A 2D model stores three components (Ux, Uz, Ry), so it shows **Fz** and
  **Mz**, with Fy and Mx at zero.
- The arrows in *Display → Show Reactions* are built from exactly these numbers.

The tab lives with Console and Results: click its header, or use this action to
raise it.
""",
            "display.reactions",
        ),
        "display.reactions_dialog": _t(
            "Display → Reactions…",
            "Display",
            "The same reactions as the tab, in a window you can close.",
            """
A modal window with one row per restrained node and the six global components
of the case on screen. It is the tab's table in a window, for reading without
switching the bottom dock over the console.

Use it when you want the numbers in front of you for a moment: the model stays
behind, and closing it puts you back where you were. For a table that stays open
beside the model, use *Display → Reactions Table*, which raises the tab.
""",
            "display.reactions_table",
            "display.reactions",
        ),
        "display.force_diagram": _t(
            "Display → Force Diagram",
            "Display",
            "Axial, shear, moment or torsion diagrams along the frame members.",
            """
Draws the element force component you pick (N, V2, V3, T, M2, M3) as a diagram
along each member, at the analysis step you pick.

# Reading it
- The end-j sign is flipped internally so a diagram is continuous across an
  element: a jump at a joint means a real discontinuity (a hinge, a point load,
  or two members with different sections).
- A member under span loads (uniform, point, trapezoidal, self weight) is drawn
  with **intermediate stations**: the internal forces follow from the end forces
  and the loads by statics, so the moment is parabolic under a uniform load and
  piecewise linear under point loads, with the shear jumping at each point, and
  the largest value between the ends is labelled. A member without a span load
  stays a straight line between its ends. Stations are drawn for the results of a
  static case; a combination or envelope (whose cases are not at hand) draws
  straight lines between the ends.
- Diagrams are drawn **between the two ends of a line element**. Shells, quads
  and other face elements have no two-end station, so they are skipped rather
  than drawn wrongly; if no line element returned forces the log says so.
- The values come from the analysis results, not from a hand calculation: what
  you see is what the solver computed.
""",
            "display.deformed",
            "assign.distributed_load",
            "display.shell_contours",
        ),
        "display.shell_contours": _t(
            "Display → Shell Contours",
            "Display",
            "A colour map of the shell faces: deformations, forces, moments and their principals.",
            """
Paints one quantity on the shell faces, with a colour bar, on the results of the
last static analysis.

# What can be shown
- **Deformation** — `|u|`, `ux`, `uy`, `uz`. These warp the mesh, so the colour
  and the shape say the same thing; the scale box multiplies the displacement
  (`0` paints the undeformed model).
- **Membrane** — `N11`, `N22`, `N12` and the principal values `N1`, `N2`
  (force per unit length).
- **Bending** — `M11`, `M22`, `M12` and `M1`, `M2` (moment per unit length).
- **Shear** — `V13`, `V23` and their magnitude `V`.

# Principal values and directions
`N1`/`N2` and `M1`/`M2` are the eigenvalues of the symmetric 2×2 membrane and
bending tensors — Mohr's circle, computed in `core.shell_results`. They do not
depend on the element's local axes, which is why they are the right thing to
read a design from: the frame of the mesh is arbitrary, the principal value is
not. Turning on **Draw principal directions** adds one segment per element
through its centroid, along the major principal axis, with a length proportional
to the spread between the two values — where the two are equal there is no
direction, and nothing is drawn.

# Limits worth knowing
- A field is painted on the **shell faces** (`ShellMITC4`, quads). Bars are not
  part of the map, and a model without shells cannot show one.
- Values are the **section stress resultants** OpenSees reports, averaged over
  the element's gauss points and onto the nodes for a continuous picture. They
  are per unit length, so a membrane force reads `N/m` (or `kip/in`) and a
  moment `N·m/m` (or `kip·in/in`).
- A **frame model has nothing to paint**: bars have no section resultants, so
  the contour needs at least one shell or quad. The command says so instead of
  showing an empty map.
""",
            "display.deformed",
            "display.force_diagram",
            "mechanics.fiber_sections",
        ),
        "display.time_history": _t(
            "Display → Time History",
            "Display",
            "A response plotted against time from a transient case.",
            """
Choose one or more nodes or elements and the component to plot; each becomes a
curve on the same axes so they can be compared.

- Node displacement, velocity and acceleration, and element forces are available
  as far as the recorders saved them.
- The plot is interactive (zoom, pan) and the axes are labelled in the project's
  display units.
- Peak values are easier to read off the tables (Display → Results panel, with a
  full-precision CSV export) than off the plot.
""",
            "mechanics.transient",
            "display.export_animation",
        ),
        "display.export_animation": _t(
            "Display → Export Time-History Animation",
            "Display",
            "An MP4 (or GIF) of a transient response.",
            """
Exports the deformed shape over the steps of a transient case as an animation,
so a response can be shown to someone else.

- MP4 needs FFmpeg (through `imageio`); GIF always works and is the fallback the
  error message suggests.
- The frame rate and the deformation scale are the values to set: too fast hides
  the response, too slow makes a large file.
- Exporting renders one frame per step: a long record at a small time step is a
  lot of frames, so it is worth narrowing the step range first.
""",
            "display.time_history",
            "display.deformed",
        ),
        "display.hysteresis": _t(
            "Display → Hysteresis",
            "Display",
            "Force against displacement for an element or a node, over a transient.",
            """
Plots one response against another (force vs displacement, moment vs rotation)
along the time history. That loop is where the energy dissipation of an element
is read: its enclosed area is the energy absorbed per cycle.

- Typical pairs: an isolator's shear force against its relative displacement (the
  bilinear loop), a plastic hinge's moment against rotation, a base shear
  against a roof displacement.
- A loop that is a straight line means the element stayed elastic; a loop that
  pinches means the model is degrading.
""",
            "display.time_history",
            "mechanics.isolators",
        ),
        "display.pushover": _t(
            "Display → Pushover Curve",
            "Display",
            "Base shear against the control displacement.",
            """
The capacity curve of a pushover case: what the structure carried as it was
pushed. The axes are labelled in the project's display units.

# Reading it
- The initial slope is the elastic stiffness; a kink is first yield; a softening
  branch means a mechanism is forming.
- The values come from the case's own recorders: the base shear is the sum of the
  support reactions in the pushed direction, at every step.
- A curve that stops early stopped converging — the log says at which step and
  why, and the results keep what was computed.
""",
            "mechanics.pushover",
            "analyze.cases",
        ),
        "display.response_spectrum": _t(
            "Display → Response Spectrum",
            "Display",
            "The combined modal response, and the spectrum behind it.",
            """
Shows the spectrum a response-spectrum case used (a code spectrum, a target
spectrum or one computed from a record) and the structure's response combined by
the case's rule.

- The combination rule (SRSS or CQC) and the damping are the case's settings; the
  plot reports which was used.
- The modal contributions are listed so the dominant modes are visible, which is
  also how you check that enough modes were asked for.
- The result is an envelope of maxima, not a time history: nothing here says when
  the peak occurs.
""",
            "mechanics.response_spectrum",
            "analyze.cases",
        ),
        "display.options": _t(
            "Display → Display Options",
            "Display",
            "Labels, masses and the on-screen size of model markers.",
            """
Toggles the annotations and the heavy overlays:

- **Node labels** and **element labels** — the name, or `N#`/`E#` when there is
  none. **Label height** sets their text size separately, in pixels.
- **Joint masses** — a purple diamond at every joint with a non-zero lumped
  mass. Off by default because most models carry mass on many joints.
- **Nodes, Supports, Load arrows, Reactions, Masses, Releases** — each marker
  can be a percentage of the viewport height. The renderer converts that
  percentage to world units with the camera, so the marker keeps the same size
  on screen at every zoom level. Release dots are screen-space points like the
  nodes. The values are per viewport and travel with the project.
- **Section extrusions** (View → Show Extruded Sections) — each member's real
  cross section (I, channel, tee, tube, pipe, angle, fibre patches) swept along
  it, so the physical footprint and the local axes are visible.
- The **reference triad** at the origin (coloured X, Y and Z arrows) is not a
  toggle: it is small, scaled to the model, and it is what tells you which way
  the elements run in an isometric view.
""",
            "view.show_extruded",
            "options.units",
        ),
        "display.back_to_model": _t(
            "Display → Back to Model",
            "Display",
            "Leave a results view and return to the undeformed model.",
            """
Clears the result overlay (deformed shape, mode shape, diagram) and returns the
canvas to the model, where clicking selects and the draw tools work. The results
are not discarded: any Display command brings them back.
""",
            "display.deformed",
        ),
        # ──────────────────────────── View ────────────────────────────
        "view.zoom_extents": _t(
            "View → Zoom Extents",
            "View",
            "Fit the whole model in the viewport.",
            """
Frames the camera on everything in the model. Worth using after an import or a
generation: a model built from a drawing can be anywhere in space, and this is
how it comes back into view.
""",
            "view.iso",
        ),
        "view.iso": _t(
            "View → Isometric",
            "View",
            "A 3D view with no working plane: clicking snaps in space.",
            """
The free 3D view. No working plane is active, so the draw tools snap to the full
3D grid rather than to a single level; that is the right mode for a space frame
and the wrong one for drawing a plan.

The coloured triad at the origin (red X, green Y, blue Z) is there to keep the
orientation obvious.
""",
            "view.top",
            "view.front",
        ),
        "view.top": _t(
            "View → Top (XY)",
            "View",
            "Plan view: looking down -Z, working plane Z = level.",
            """
Looks down the Z axis and makes the XY plane the working plane. The Level combo
then lists the Z ordinates of your grids, so you draw on the storey you choose.

- In a 2D project this is the view of the model's own plane (a 2D frame lives in
  XY), and it is what the portal frame wizard switches to.
- Only the active level's grid lines and intersections are drawn while a plane is
  active, which keeps a plan readable.
""",
            "view.iso",
            "define.grid",
        ),
        "view.front": _t(
            "View → Front (XZ)",
            "View",
            "Elevation view: looking down -Y, working plane Y = level.",
            """
Looks down the Y axis and makes the XZ plane the working plane — the elevation
view in a Z-up model, and where frames are usually drawn. The Level combo lists
the Y ordinates.
""",
            "view.right",
            "define.portal_frame",
        ),
        "view.right": _t(
            "View → Right (YZ)",
            "View",
            "Side elevation: looking down -X, working plane X = level.",
            """
Looks down the X axis and makes the YZ plane the working plane: the other
elevation, with the Level combo listing the X ordinates. Useful to check a
building's depth and to draw the frames that run along Y.
""",
            "view.front",
        ),
        "view.parallel": _t(
            "View → Parallel Projection",
            "View",
            "Orthographic instead of perspective.",
            """
Parallel projection keeps parallel lines parallel and sizes independent of
distance. It is the usual choice for engineering drawings: a dimension in the
view corresponds to a dimension in the model, whatever the depth.

Perspective is easier to read for a complex 3D model; the toggle is a display
setting only and never affects the analysis.
""",
            "view.iso",
        ),
        "view.show_extruded": _t(
            "View → Show Extruded Sections",
            "View",
            "Draw each member with the true shape of its section.",
            """
Sweeps each frame element's cross section along its axis, semi transparently,
with the outline drawn at both ends and along every corner. What is drawn:

- **AISC shapes** (Define → Sections → AISC) — the real profile: an I for W, HP,
  M and S, a channel for C and MC, a tee for WT, MT and ST, a rectangular or
  round tube for HSS and Pipe, an angle for L. Fillets and corner radii are left
  out. A section added before this version has no profile stored: add the shape
  again to see it.
- **Fibre sections** — their rectangular and circular patches as they are
  (a reinforced concrete column shows its cover and core).
- **Rectangular concrete sections** from the wizard — the rectangle.
- **Anything else** whose size is known — the rectangle with the same area and
  second moments (an elastic section typed in by hand, a beam with hinges, a
  fibre section made of single fibres). A truss with only an area is the round
  bar of that area.

The section stands in the member's own local axes, the ones OpenSees uses, and
sits on its insertion point (Assign → Frame → Insertion Point). Two things become
visible that are hard to see otherwise:

- the **physical footprint** — whether members overlap or fit;
- the **orientation** — which way the strong axis of each member bends, which is
  what the distributed load components and the diagram signs refer to.
""",
            "display.options",
            "assign.geom_transf",
        ),
        "view.visibility": _t(
            "View → Visibility",
            "View",
            "Show or hide model categories in this viewport.",
            """
One checkbox per category: grids, nodes, frames, shells, restraints, constraints,
frame assignments, releases, loads, node and element labels, and extruded
sections. A change is **per viewport** - the model keeps every entity, so the
tree, the analysis and the other views are unaffected.

**Releases** draws a colored dot on each released member end: violet for
torsion, orange for M2, red for M3, and yellow for partial fixity. A release
with more than one action shows one staggered dot per action. It is separate
from **Frame Assignments**, which draws the rigid end-offset bars.

- **Hide Selected** (Ctrl+H) hides what is selected now, adding it to what is
  already hidden.
- **Isolate Selected** (Ctrl+Shift+I) shows only the selection: selected
  elements keep their joints visible, and every other object is hidden. It is
  also in the right-click menu.
- **Invert Visible** swaps the two sets: what is drawn disappears and what was
  hidden comes back.
- **Show All Objects** restores everything. A box selection never picks what is
  hidden in this viewport.

Hiding is how to look inside a dense model (the framing under a slab, the inside
of a wall of shells) without deleting or filtering anything.
""",
            "view.colors",
            "view.grid_line_view",
        ),
        "view.colors": _t(
            "View → Colors",
            "View",
            "Change the viewport background and entity colours.",
            """
Six colours, all per viewport: background top and bottom (the gradient behind
the model), nodes, frames, shells, and the selection highlight. Useful when a
model is projected or printed and the default palette does not read well, and to
tell two viewports apart at a glance.
""",
            "view.visibility",
            "display.options",
        ),
        "view.new_window": _t(
            "View → New View Window",
            "View",
            "Open a second viewport on the same project.",
            """
Each window is an independent viewport: its own camera, colours and Visibility
toggles. The model is shared, and so is the selection — clicking a joint or an
element highlights it in **every** window at once, which is how two angles of the
same model stay in step while you work.

Use it to keep a plan view and an isometric one side by side, or to put one
window on a second monitor. The file stores the primary window's display
settings; secondary windows live for the session.
""",
            "view.visibility",
            "view.colors",
        ),
        "view.close_window": _t(
            "View → Close View Window",
            "View",
            "Close the viewport the View menu is acting on.",
            """
Closes the active secondary viewport. The main window's viewport cannot be
closed, and closing the main window closes every secondary one with it.
""",
            "view.new_window",
        ),
        # ──────────────────────────── Options and Help ────────────────────────────
        "options.solver": _t(
            "Options → Solver",
            "Options",
            "Which engine solves the model, and where OpenSeesPy is installed.",
            """
OpenSees Studio models; an **engine** solves. The engine is **OpenSeesPy 3.8**,
a separate program with its own license, and the application can be installed
without it. Without a solver you can still model, export the OpenSeesPy script
or IFC, and write a report; Run, Check Model Stability and the Material Tester
wait for one. The log says at start whether a solver was found.

# Where OpenSeesPy comes from
- **Installed with OpenSees Studio** — in the application's own Python
  environment (`pip install opensees-studio[opensees]`, or a bundle that
  carries it).
- **Another Python** of the same version as the application (3.12) that has
  `openseespy` installed (`python -m pip install openseespy==3.8.0.0`). Choose
  its interpreter; the application asks it where its `openseespy` is, without
  starting OpenSees.
- **A folder** that contains the `openseespy` package (a `site-packages`
  folder).
- **Download OpenSeesPy from PyPI** — the button shows the OpenSeesPy license
  first and downloads only once you tick that you accept it. It fetches the two
  files OpenSeesPy publishes for this platform (Linux x86-64, Windows, macOS on
  Apple silicon), checks each against its published SHA256 digest, unpacks them
  into the application data folder and selects that folder. Cancel stops it
  and leaves nothing behind.
The status line says whether that choice is usable and which version it finds.
When the application's own environment has OpenSeesPy, it is used and another
folder is not.

# License
OpenSeesPy is free for research, education and internal use; commercial
redistribution needs a license from its authors. OpenSees Studio is free
software and does not distribute OpenSeesPy, not even in its downloadable
bundle: each user installs it, from the place its authors publish it, and should
check that their use fits its terms.

# Engine
The **Engine** list shows every engine installed, with the analysis types it
runs.

- **OpenSeesPy** — every analysis type: static, modal, transient, pushover,
  response spectrum, influence lines; nonlinear materials, fibre sections,
  hinges, bearings, shells. A separate download with its own license.
- **PyNite** — ships with OpenSees Studio (MIT license), no download. Linear
  static cases of elastic frames (elastic sections, Euler-Bernoulli) and
  trusses (elastic material), with nodal, uniform, trapezoidal, floor and
  point loads, self weight, moment and torsion releases and support springs;
  **P-Delta** when a member uses the PDelta transformation. It matches
  OpenSeesPy to rounding on those models. It refuses, with a message saying
  what, anything else: shells, zero-length elements, bearings and links,
  constraints, rigid links and diaphragms, partial fixity, end offsets, shear
  areas, surface / temperature / imposed-displacement loads, corotational
  members, and a joint lying inside a member it is not connected to (PyNite
  would connect it — use Edit → Divide Frames at Joints). Its P-Delta iterates
  on the whole model, so it is closer to the exact second-order answer than a
  single OpenSees element with the PDelta transformation, which leaves out the
  member's own P-delta. More engines plug in as Python packages (the `opensees_studio.engines`
entry point). A case of a type the chosen engine does not run is refused when
you run it, with a message naming the engine and what it does run. The
stability check and the Material Tester always use OpenSeesPy, so they stay
available (or not) whatever engine you choose.
""",
            "analyze.run",
        ),
        "edit.delete_loads": _t(
            "Edit → Delete Loads",
            "Edit and tools",
            "Remove loads by type, by load pattern, from the selection or the whole model.",
            """
# Values
- **Delete from** — the selection, or the entire model. A joint load goes with
  its joint, a frame or shell load with its element, a floor load when all four
  of its corner joints are selected.
- **Load types** — tick the ones to remove; the number next to each is how many
  the current choice would remove: joint forces and moments, imposed joint
  displacements, uniform / trapezoidal / point frame loads, frame temperature
  loads, shell pressures, floor loads, and the self weight (the pattern's
  self-weight multiplier is set to 0; only on the entire model, since it belongs
  to no joint or element).
- **Load patterns** — the patterns to remove them from (all, to start with).

Everything removed comes back with one Ctrl+Z. The log says what was removed.
""",
            "assign.load",
            "assign.distributed_load",
            "define.plain_pattern",
        ),
        "view.color_by": _t(
            "View → Color By",
            "View",
            "Paint frames and shells by section, by material or by group.",
            """
Each viewport chooses its own colouring; a legend in its upper-right corner says
which colour is which (at most 15 entries are listed).

# Entries
- **Single Colour** — every frame in the frame colour, every shell in the shell
  colour (View → Colors…).
- **By Section** — one colour per section; a BeamWithHinges member with two hinge
  sections gets the colour of the pair. Members with no section (trusses) keep
  the frame colour, listed as "(no section)".
- **By Material** — one colour per material, followed through the section: a
  reinforced-concrete fibre section is "concrete + steel". A truss is coloured by
  its own material.
- **By Group** — each group in its own colour (Define → Groups); an element in
  several groups takes the first one in the list, and one in none is "(no
  group)".

The selection is still drawn in the selection colour on top of the categories.
The choice is saved with the project, like the other display settings of the
main viewport.
""",
            "view.colors",
        ),
        "view.rotate": _t(
            "View → Rotate",
            "View",
            "Turn the point of view a step at a time, or keep it turning.",
            """
The model does not move: the camera turns about the point it looks at.

# Entries
- **Rotate Left / Right** (Alt+Left / Alt+Right) — 15° about the vertical axis.
- **Tilt Up / Down** (Alt+Up / Alt+Down) — 15° about the horizontal screen axis.
- **Spin** — keeps turning about the vertical axis until you switch it off, to
  present the model. Zoom and the other view buttons still work while it turns.

Turning the camera leaves a plan or elevation view (Top, Front, Right), so the
working plane and the Level list are cleared, as Isometric does; pick the plane
view again to draw on a level. The buttons are also in the View toolbar.
""",
            "view.iso",
        ),
        "options.units": _t(
            "Options → Set Display Units",
            "Options",
            "The unit system results are shown in.",
            """
Chooses the unit system displayed numbers are converted to (reactions,
diagrams, tables, plots). It does **not** change the model: the solver works with
the numbers you typed, in whatever system they are consistent with.

- Change it to read a result in another system (a kN·m moment as kip·ft, for
  instance) without touching the model. Every open result view is refreshed on
  the spot: diagram values, displacement tables and curves all move together
  with their unit labels.
- Forces, moments (force × length) and stresses (force / length²) each convert
  with the factors their combination implies, so the numbers stay physical.
- It is also the system used when a dialog converts a value that arrives from
  outside (an imperial shape into the project).
- See **Units and the solver** for why the application never converts the numbers
  you type.
""",
            "concepts.units",
        ),
        "help.contents": _t(
            "Help → Help Contents (F1)",
            "Help",
            "This window, on the contents page.",
            """
Opens the help at the contents page. **F1** does the same from anywhere, and it
is the key worth remembering:

- with a menu open, it opens the page of the item under the cursor;
- inside a dialog that declares one, it opens that dialog's page;
- otherwise it opens the contents.

The topic tree on the left is the whole manual; the box above it filters by title,
summary and text. Links inside a page jump between related topics.
""",
            "index",
            "help.about",
        ),
        "help.about": _t(
            "Help → About",
            "Help",
            "Version, licence and where the code lives.",
            """
Shows the application version (the same string the exported scripts carry) and
the project's home. The version matters when reporting a problem: the changelog
next to the source lists what changed, release by release.

**F1** opens this help window from anywhere — while a menu is open it opens the
help of the item under the cursor, and inside a dialog it opens that dialog's
page.
""",
            "index",
        ),
        "help.performance": _t(
            "Help → Performance monitor",
            "Help",
            "Measure imports, analysis, rendering and UI stalls on large models.",
            """
The performance monitor is **opt-in**: normal work pays essentially nothing.
Enable it in any of these ways:

- launch with ``opensees_studio --profile`` (frozen builds: ``OpenSeesStudio.exe --profile``);
- launch with ``--perf-json report.json`` to also write a report on exit;
- set ``OPENSEES_STUDIO_PERF=1`` in the environment;
- open this dialog and press **Enable profiling**.

The table lists every instrumented boundary with its last, total, count, p95 and
maximum milliseconds. Names are grouped by prefix: ``s2k.*`` for the SAP2000
importer, ``persistence.*`` for project I/O, ``analysis.*`` for the solver,
``render.*`` for scene construction, and ``command.*`` for undoable edits.

**Profile next action** runs the next instrumented operation under ``cProfile``
and shows the 30 functions with the largest cumulative time. **Save JSON** and
**Copy JSON** produce a report with the version, platform, model counts, memory
and timings, suitable for attaching to an issue.

For repeatable measurements of large synthetic models, run
``python tools/perf_bench.py --size large --profile``. See
``docs/performance-profiling.md`` for the full workflow.
""",
            "help.contents",
        ),
    }
)

# ──────────────────────────── Annex: OpenSees command glossary ────────────────────────────
TOPICS.update(
    {
        page_id: _t(title, GLOSSARY_GROUP, summary, body, *see_also)
        for page_id, title, summary, body, see_also in glossary_pages()
    }
)

#: Menu action (attribute name on the main window) → topic.
# ──────────────────────────── Buildings ────────────────────────────
TOPICS.update(
    {
        "define.storeys": _t(
            "Define → Storeys",
            "Define",
            "Name the floor levels of a building and their elevations.",
            """
A storey is a floor level: a name and an elevation along the vertical axis, Z
(in 2D and in 3D). The storey table, the "every joint of storey N" diaphragm and the
drift ratios all read them.

# Values
- **Name**, **Elevation** — one row per floor. Everything below the lowest
  storey is the **base**, whose elevation is the lowest node of the model.
- **From Z grid lines** — one storey per Z line of the chosen coordinate system,
  the lowest line being the base (Story1, Story2... as ETABS names them). Rows
  already there keep their ids, so diaphragms that follow a storey keep it.

# Notes
- A storey's **height** is the distance to the storey (or base) below it: the
  inter-storey drift ratio divides by it.
- A joint belongs to a storey when it lies on its elevation, to a millionth of
  the model's height.
- A storey used by a diaphragm cannot be removed; delete the diaphragm first
  (Assign → Joint → Remove Constraints on its retained node).
""",
            "assign.diaphragm",
            "mechanics.buildings",
        ),
        "define.groups": _t(
            "Define → Groups",
            "Define",
            "Named sets of joints and elements, to select a part of the model again.",
            """
A group is a name, a colour and the joints and elements it holds, as in SAP2000
and ETABS. Groups carry no mechanics: they let you pick a part of the model again
later. A joint or an element can belong to any number of groups.

# Values
- **Name** — unique, compared without case. **Colour** — click to change it.
- **Joints**, **Elements** — how many each group holds (read only). Fill them
  with Assign → Assign to Group.
- **Add** / **Remove** — a new empty group, or remove the selected rows. Removing
  a group never deletes its joints or elements.

# Notes
- Deleting a joint or an element takes it out of every group; Undo puts it back.
  Fixing duplicates moves a merged joint's membership to the joint that is kept.
- Select → By Group selects a group's members (adding to the selection).
""",
            "assign.group",
            "select.menu",
        ),
        "define.section_cuts": _t(
            "Define → Section Cuts",
            "Define",
            "The resultant force through a part of the model, defined by a group.",
            """
A section cut, as in SAP2000, sums the end forces of a group's **elements** at
the group's **joints**, with the moments taken about the centroid of those joints
or about a point you type. Put in the group the elements the cut passes through
and the joints on the side you want the force at:

- the columns of a storey and their base joints: the storey (or pier) shear,
  axial force and overturning moment;
- a wall's shells and the joints of one edge: the force through that edge.

# Values
- **Name** — unique. **Group** — from Define → Groups.
- **Centre X, Y, Z** — the point the moments are about; leave all three empty
  for the centroid of the cut joints.

# Results
A static case gets a **Section cuts** tab in the Results panel: the six global
components Fx, Fy, Fz, Mx, My, Mz (a 2D model: F1, F3, M2) at the final step.
The sign is that of the loads on the elements' side of the cut: a cantilever
column with a lateral load P and a weight W at its top, cut at its base, reports
+P and -W. Checked against hand statics in 2D and 3D.

# Notes
- Re-run the cases after adding or changing a cut. Pushover, transient and
  response spectrum cases, and load combinations, do not report cuts yet.
- A group a cut uses cannot be removed; delete the cut first.
- An element of the group that touches no joint of the group adds nothing; two
  group elements meeting at a free group joint cancel.
""",
            "define.groups",
            "display.select_results",
        ),
        "assign.group": _t(
            "Assign → Assign to Group",
            "Assign — groups",
            "Add the selected joints and elements to a group, remove them, or replace it.",
            """
Works on the current selection (Ctrl+Shift+G).

# Values
- **Group** — an existing group, or **New group…** with the name typed below.
  A new group gets the next colour and takes the selection.
- **Add to group** — the selection joins the group's members.
- **Remove from group** — the selected joints and elements leave the group.
- **Replace members** — the group holds exactly the selection afterwards.

Creating the group and filling it are one undo step.
""",
            "define.groups",
            "select.menu",
        ),
        "define.seismic_loads": _t(
            "Define → Seismic Loads (Equivalent Lateral Force)",
            "Define",
            "Base shear by the code, shared between the storeys, written as load cases.",
            """
Computes the equivalent lateral force (ELF) loads of ASCE/SEI 7-16 or TBDY 2018
and writes them as load patterns with linear static cases, one per direction:
`EQ X`, `EQ Y` and, with accidental eccentricity, `EQ X +e`, `EQ X -e`,
`EQ Y +e`, `EQ Y -e`. A Plain pattern already named that way (for instance the
empty `EQ X` the combination generator creates) gets its nodal loads replaced, so
the cases and combinations that use it keep working. Everything is one undo step.

# Values
- **Code** — ASCE/SEI 7-16 §12.8 or TBDY 2018 §4.7. SDS, SD1, S1 and TL are taken
  from the project's design spectrum (Ground Motions → Target spectrum) when it has
  one.
- **SDS, SD1** (g) — the design spectral accelerations. **S1** (ASCE) only drives
  the near-fault minimum of Eq. 12.8-6. **TL** — the long-period transition.
- **R** and **Ie** (ASCE) or **R**, **I** and **D** (TBDY) — the structural system's
  coefficients. They are yours to choose; the generator only applies the formulas.
- **Period T** — typed, or **Approximate**: ASCE Ta = Ct hn^x (Table 12.8-2) or
  TBDY T = Ct H^(3/4) for the chosen system, with the height of the model. A
  modal period can be typed in; ASCE limits it to Cu Ta, which is left to you.
- **Directions** — X and/or Y (a 2D model lives in the X-Z plane: X only).
- **Accidental eccentricity ±** — the storey force moved by ± the ratio (5 %)
  times the floor's extent across the load (3D).

# How it is computed
- **ASCE 7-16**: Cs = SDS / (R/Ie), at most SD1 / (T R/Ie) (or SD1 TL / (T² R/Ie)
  past TL), at least max(0.044 SDS Ie, 0.01) and, for S1 ≥ 0.6 g,
  0.5 S1 / (R/Ie). V = Cs W, and Fx = V wx hx^k / Σ wi hi^k with k = 1 up to
  0.5 s, 2 from 2.5 s and linear between. The preview names the clause that
  governs.
- **TBDY 2018**: Vt = W SaR(T) with SaR = Sae(T) / Ra(T), Ra = R/I past TB and
  D + (R/I - D) T/TB below it, and Vt ≥ 0.04 I SDS W. ΔFN = 0.0075 N Vt acts
  at the top; the rest is shared as Fi = (Vt - ΔFN) wi Hi / Σ wj Hj.
- **Weights** are the masses the analysis uses (typed masses, Define → Mass
  Source, diaphragm lumping) times g, at the storeys (Define → Storeys) or, with
  none defined, at every elevation above the base that carries mass. Heights are
  from the base. Mass that lies off the storey levels is left out of W, and the
  preview says how much.
- **Where the force goes**: to a horizontal diaphragm's retained node when that is
  where the floor's mass is (with the eccentricity as a torque F e about Z), else
  to the floor's joints in proportion to their mass (tilted so that the resultant
  acts e off the centre of mass).

Run the `EQ X` / `EQ Y` cases like any other static case, and combine them with
Define → Load Combinations (the code generators take them as Earthquake loads).
""",
            "define.mass_source",
            "define.storeys",
        ),
        "define.mass_source": _t(
            "Define → Mass Source",
            "Define",
            "Turn self weight and load patterns into nodal mass (W / g).",
            """
The mass source is SAP2000's and ETABS': instead of typing a mass at every
joint, the solver gets **W / g** of what you choose. Masses typed with Assign →
Joint → Masses always count on top.

# Values
- **Element self mass** — frames and shells whose section has a unit weight,
  lumped half on each end of a frame and by tributary area on a shell's corners.
- **Load patterns** — tick a pattern and give its factor (the usual D + 0.3 L
  is DEAD 1.0, LIVE 0.3). Only the **downward** part of its nodal, uniform and
  point loads counts, plus its self-weight multiplier; element loads go to the
  element's ends. A node whose total comes out upward gets nothing.
- **Also on the vertical translation** — by default the mass goes on the
  lateral translations only, so the model has no vertical modes.
- **Lump at the retained node** — each rigid diaphragm's in-plane mass and its
  rotational inertia sum(m r²) move to the retained node, where the storey table
  and mass participation report them.

# Mechanics
Lumping is exact only when the retained node sits at the centre of that mass;
otherwise the rigid-body mass couples translation and rotation, which a lumped
mass cannot express, so such a diaphragm keeps its mass on the joints (the
constraint carries it exactly). The periods are the same either way. A restrained
DOF gets no mass: it never moves, and it would only dilute the mass ratios.

A pattern that carries self weight together with **Element self mass** counts
the self weight twice; the dialog warns about it.
""",
            "assign.masses",
            "mechanics.buildings",
        ),
        "assign.diaphragm": _t(
            "Assign → Joint → Diaphragm",
            "Assign — joints",
            "A floor rigid in its own plane (OpenSees rigidDiaphragm).",
            """
Every constrained joint follows the **retained** node in the two in-plane
translations and the rotation about the perpendicular axis; the out-of-plane
DOF stay free, so slabs still bend and columns still shorten.

# Values
- **Joints** — every joint of a storey (resolved when the model is built, so
  joints drawn later join the floor; supports in the plane are left out), or the
  selected joints.
- **Perpendicular axis** — Z for a floor; X or Y for a vertical rigid plane.
- **Retained node** — a new node at the centre of mass of the joints (their
  effective mass, the mass source included), or an existing selected node.

# Mechanics
A retained node that no element touches has no stiffness out of its plane: the
runner fixes those three DOF itself, OpenSees' own recipe. A case left at the
**Plain** constraint handler runs with **Transformation**: Plain drops a
diaphragm with a warning and then solves a singular system without reporting
failure. A joint can belong to one diaphragm only, and not also be the
constrained node of an equalDOF or rigid link; a joint out of the plane is
refused (OpenSees would silently drop it).

A joint of the diaphragm may not **retain** another constraint either: no
equalDOF or rigid link retained by it. The Transformation handler cannot chain
such constraints (it keeps one per node and numbers the chained one wrong) and
gives wrong results without an error, so the model check refuses them; leave
that joint out of the floor.

**Frame end releases** at a diaphragm joint work, without such a chain:

- an elastic beam-column with an elastic section is released inside the element
  (`-releasez` / `-releasey` for M3 / M2, a zero `G J` for torsion), exactly, and
  at the face of a rigid end zone when the end is offset;
- any other member with elastic properties (and an elastic beam-column with a
  point, partial or trapezoidal load, a consistent mass matrix, or partial
  fixity at that end, which OpenSees cannot condense) hangs the end off a hidden
  node held by penalty springs 10^5 times the member's own stiffness: results
  within about 10^-7 of the exact ones;
- a fibre member, or such a spring-held end with an end offset, is refused with
  a remedy.

The canvas draws the diaphragm as spokes from the retained node (a small cube).
Deleting the retained node deletes the diaphragm.
""",
            "define.storeys",
            "define.mass_source",
            "mechanics.constraints",
            "assign.remove_constraints",
        ),
        "assign.rigid_link": _t(
            "Assign → Joint → Rigid Link",
            "Assign — joints",
            "Tie two joints with OpenSees rigidLink (beam or bar).",
            """
# Values
- **beam** — the constrained node moves with the retained one as a rigid body:
  its translations include the rotation times the lever arm, and its rotations
  equal the retained node's. Needs rotations (ndf 3 in 2D, 6 in 3D).
- **bar** — only the translations are tied, as an inextensible bar would.
- **Retained / constrained node** — the two selected joints.

# Mechanics
Like a diaphragm, a rigid link is a constraint the Plain handler cannot enforce,
so the case runs with Transformation. The canvas draws it as a thick orange bar.

The retained node must not itself be constrained (unless by an equalDOF of every
DOF), and the constrained node takes no other constraint: see equalDOF. Two rigid
beam links in a row are one rigid link from the first node to the last.

A frame end released at the constrained node is made without a further
constraint, as at a diaphragm joint (see Assign → Frame → Releases/Partial
Fixity).
""",
            "mechanics.constraints",
            "assign.remove_constraints",
        ),
        "assign.remove_constraints": _t(
            "Assign → Joint → Remove Constraints",
            "Assign — joints",
            "Take the selected joints out of every equalDOF, rigid link and diaphragm.",
            """
Removes every equalDOF and rigid link that touches a selected joint, every
diaphragm whose retained node is selected, and the selected joints from the
diaphragms that list them (a diaphragm left without joints goes too). A storey
diaphragm keeps following its storey: select its retained node to remove it.
Undo puts everything back.
""",
            "assign.diaphragm",
            "assign.rigid_link",
        ),
        "mechanics.buildings": _t(
            "Buildings: storeys, diaphragms and the storey table",
            "Mechanics",
            "Storey displacement, drift ratio, storey shear and base shear.",
            """
With storeys defined, the Results panel shows a **Storeys** tab (exported to CSV
at full precision like every table): top storey first, the base last.

# What each column is
- **U** — the storey's lateral displacement: the retained node of its diaphragm,
  or the mean of its joints when it has none.
- **Drift** — (U of the storey - U of the level below) / storey height.
- **Shear** — static case: the force the members cut just above the level below
  carry, from their global end forces. Base row: minus the sum of the lateral
  reactions, the base shear.
- **Response spectrum** — each mode's displacement, drift and storey shear (its
  inertia forces w² m u above the cut) is combined by the case's SRSS or CQC
  rule. A peak drift is not the difference of two peak displacements.
- **Modal** — the storey values of each mode shape, as OpenSees normalises it.
- **Pushover** — the last step's displacements and drifts.

# Building a building
Define → Storeys (from the Z grid lines), Assign → Joint → Diaphragm on each
storey with a new node at the centre of mass, Define → Mass Source, then a
modal and a response spectrum case. The example
`building_3storey_diaphragm.osmodel` is all of this, checked against a
hand-built OpenSeesPy model.
""",
            "define.storeys",
            "assign.diaphragm",
            "define.mass_source",
            "mechanics.response_spectrum",
        ),
    }
)


ACTION_TOPICS: dict[str, str] = {
    # ── File ────────────────────────────────────────────────────────
    "_act_new": "file.new",
    "_act_new_2d": "file.new_2d_frame",
    "_act_new_2d_truss": "file.new_2d_truss",
    "_act_open": "file.open",
    "_act_save": "file.save",
    "_act_save_as": "file.save_as",
    "_act_import_dxf": "file.import_dxf",
    "_act_import_s3d": "file.import_s3d",
    "_act_import_s2k": "file.import_s2k",
    "_act_steel_check": "design.steel_check",
    "_act_influence_line": "display.influence_line",
    "_act_drift_check": "design.drift_check",
    "_act_steel_ratios": "design.steel_ratios",
    "_act_export_script": "file.export_script",
    "_act_export_ifc": "file.export_ifc",
    "_act_export_s2k": "file.export_s2k",
    "_act_export_report": "file.export_report",
    "_act_run_batch": "file.run_batch",
    "_act_quit": "file.quit",
    # ── Edit and tools ──────────────────────────────────────────────
    "_act_undo": "edit.undo",
    "_act_redo": "edit.redo",
    "_act_delete": "edit.delete",
    "_act_clear_selection": "edit.clear_selection",
    "_act_select_all": "edit.select_all",
    "_act_table_editing": "edit.table_editing",
    "_act_invert_selection": "select.menu",
    "_act_previous_selection": "select.menu",
    "_act_select_all_joints": "select.menu",
    "_act_select_all_elements": "select.menu",
    "_act_select_supports": "select.menu",
    "_act_select_joints_with_mass": "select.menu",
    "_act_select_joints_of_elements": "select.menu",
    "_act_select_elements_within_joints": "select.menu",
    "_act_select_weighted": "select.menu",
    "_act_move": "edit.move",
    "_act_replicate": "edit.replicate",
    "_act_check_duplicates": "edit.check_duplicates",
    "_act_mesh": "edit.mesh",
    "_act_merge_joints": "edit.merge_joints",
    "_act_divide_frames": "edit.divide_frames",
    "_act_select_loose_joints": "select.menu",
    "_act_select_joints_in_bars": "select.menu",
    "_act_select_shell_edge_joints": "select.menu",
    "_act_mirror": "edit.mirror",
    "_act_tool_select": "tools.select",
    "_act_tool_draw_node": "tools.draw_node",
    "_act_tool_draw_frame": "tools.draw_frame",
    "_act_tool_draw_truss": "tools.draw_truss",
    # ── Define ──────────────────────────────────────────────────────
    "_act_grid": "define.grid",
    "_act_grid_wizard": "define.grid_wizard",
    "_act_show_grids": "view.grids",
    "_act_show_grid_labels": "view.grids",
    "_act_grid_line_view": "view.grid_line_view",
    "_act_show_all_objects": "view.visibility",
    "_act_add_node": "define.add_node",
    "_act_storeys": "define.storeys",
    "_act_groups": "define.groups",
    "_act_section_cuts": "define.section_cuts",
    "_act_assign_group": "assign.group",
    "_act_mass_source": "define.mass_source",
    "_act_seismic_loads": "define.seismic_loads",
    "_act_create_shell": "define.create_shell",
    "_act_frame_wizard": "define.portal_frame",
    "_act_truss_wizard": "define.truss",
    "_act_material_library": "define.material_library",
    "_act_friction_library": "define.friction_library",
    "_act_material_tester": "define.material_tester",
    "_act_ground_motions": "define.ground_motions",
    "_act_section_library": "define.section_library",
    "_act_concrete_section": "define.concrete_section",
    "_act_section_designer": "define.section_designer",
    "_act_add_linear_ts": "define.linear_ts",
    "_act_add_path_ts": "define.path_ts",
    "_act_add_function_ts": "define.function_ts",
    "_act_constant_ts": "define.constant_ts",
    "_act_add_multi_support": "define.multi_support",
    "_act_custom_commands": "define.custom_commands",
    "_act_assign_link": "assign.link",
    "_act_add_plain_pattern": "define.plain_pattern",
    "_act_add_uniform_excitation": "define.uniform_excitation",
    "_act_load_combinations": "define.load_combinations",
    # ── Assign: joints ──────────────────────────────────────────────
    "_act_assign_support": "assign.support",
    "_act_assign_masses": "assign.masses",
    "_act_assign_springs": "assign.springs",
    "_act_assign_equal_dof": "assign.equal_dof",
    "_act_assign_diaphragm": "assign.diaphragm",
    "_act_assign_rigid_link": "assign.rigid_link",
    "_act_remove_constraints": "assign.remove_constraints",
    "_act_assign_load": "assign.load",
    "_act_assign_imposed_displacement": "assign.imposed_displacement",
    "_act_assign_surface_load": "assign.surface_load",
    "_act_assign_floor_load": "assign.floor_load",
    "_act_assign_zls": "assign.zero_length_section",
    "_act_assign_bearing": "assign.bearing",
    # ── Assign: frame ───────────────────────────────────────────────
    "_act_assign_section": "assign.section",
    "_act_assign_material": "assign.material",
    "_act_assign_geom_transf": "assign.geom_transf",
    "_act_assign_integration": "assign.integration",
    "_act_assign_distributed_load": "assign.distributed_load",
    "_act_assign_frame_point_load": "assign.frame_point_load",
    "_act_assign_releases": "assign.frame_releases",
    "_act_assign_end_offsets": "assign.end_offsets",
    "_act_assign_insertion": "assign.insertion_point",
    "_act_assign_modifiers": "assign.property_modifiers",
    "_act_assign_trapezoidal_load": "assign.trapezoidal_load",
    "_act_assign_temperature_load": "assign.temperature_load",
    "_act_assign_hinge": "assign.hinge",
    "_act_assign_wall": "assign.wall",
    # ── Analyze ─────────────────────────────────────────────────────
    "_act_case_manager": "analyze.cases",
    "_act_check_model": "analyze.check_model",
    "_act_run": "analyze.run",
    "_act_run_all": "analyze.run_all",
    "_act_run_selected": "analyze.run_selected",
    "_act_clear_results": "analyze.clear_results",
    "_act_check_stability": "analyze.stability",
    "_act_cancel_stability": "analyze.stability",
    # ── Display ─────────────────────────────────────────────────────
    "_act_select_results": "display.select_results",
    "_act_show_deformed": "display.deformed",
    "_act_show_mode_shape": "display.mode_shape",
    "_act_show_force_diagram": "display.force_diagram",
    "_act_show_reactions": "display.reactions",
    "_act_reactions_table": "display.reactions_table",
    "_act_reactions_dialog": "display.reactions_dialog",
    "_act_shell_contours": "display.shell_contours",
    "_act_show_time_history": "display.time_history",
    "_act_export_th_animation": "display.export_animation",
    "_act_show_hysteresis": "display.hysteresis",
    "_act_show_pushover": "display.pushover",
    "_act_show_response_spectrum": "display.response_spectrum",
    "_act_display_options": "display.options",
    "_act_back_to_model": "display.back_to_model",
    # ── View ────────────────────────────────────────────────────────
    "_act_zoom_extents": "view.zoom_extents",
    "_act_view_iso": "view.iso",
    "_act_view_top": "view.top",
    "_act_view_front": "view.front",
    "_act_view_right": "view.right",
    "_act_toggle_parallel": "view.parallel",
    "_act_show_extruded": "view.show_extruded",
    "_act_zoom_in": "view.zoom_extents",
    "_act_zoom_out": "view.zoom_extents",
    "_act_hide_selected": "view.visibility",
    "_act_isolate_selected": "view.visibility",
    "_act_invert_visible": "view.visibility",
    "_act_view_colors": "view.colors",
    "_act_new_view": "view.new_window",
    "_act_close_view": "view.close_window",
    "_act_vis_grids": "view.visibility",
    "_act_vis_grid_labels": "view.visibility",
    "_act_vis_nodes": "view.visibility",
    "_act_vis_frames": "view.visibility",
    "_act_vis_surfaces": "view.visibility",
    "_act_vis_supports": "view.visibility",
    "_act_vis_constraints": "view.visibility",
    "_act_vis_frame_assignments": "view.visibility",
    "_act_vis_releases": "view.visibility",
    "_act_vis_loads": "view.visibility",
    "_act_vis_node_labels": "view.visibility",
    "_act_vis_element_labels": "view.visibility",
    "_act_vis_extruded": "view.show_extruded",
    # ── Options and Help ────────────────────────────────────────────
    "_act_set_units": "options.units",
    "_act_solver_settings": "options.solver",
    "_act_delete_loads": "edit.delete_loads",
    "_act_color_none": "view.color_by",
    "_act_color_section": "view.color_by",
    "_act_color_material": "view.color_by",
    "_act_color_group": "view.color_by",
    "_act_rotate_left": "view.rotate",
    "_act_rotate_right": "view.rotate",
    "_act_rotate_up": "view.rotate",
    "_act_rotate_down": "view.rotate",
    "_act_spin": "view.rotate",
    "_act_help_contents": "help.contents",
    "_act_about": "help.about",
    "_act_performance": "help.performance",
}
