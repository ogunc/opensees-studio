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
    "Analyze",
    "Display",
    "View",
    "Options",
    "Help",
    "Mechanics",
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
3. **Analyze**: create one or more cases (Analyze → Cases) and run them
(Analyze → Run). The solve happens in a separate process, so a crash in the
solver cannot take the interface with it.
4. **Display** the results: deformed shape, mode shapes, force diagrams, time
histories, hysteresis, pushover curves and response spectra.

# Where things are
- The **3D viewport** is the model; clicking selects, dragging orbits.
- Everything is a command on an undo stack: Ctrl+Z undoes one model edit.
- Every dialog that takes numbers has a help page: **press F1** while the menu
or the dialog is open.
- The **Console** dock keeps a log of what the application did, including the
commands it emitted to OpenSees.

# What is not here
Nothing is unit-aware behind your back: see **Units and the solver**. Nothing is
solved until you ask: editing the model never starts an analysis.
""",
        "concepts.units",
        "concepts.model",
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
  in the lateral direction (DOF 1 for X, 2 for Y, 3 for Z, 4-6 for rotations).
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
Creates a planar frame project (ndm = 2, ndf = 3: Ux, Uy, Rz per joint) and
immediately opens the **Portal Frame Wizard**. The frame is built on the XY
plane, which is the only plane a 2D model has, and the wizard also writes the
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
Creates a project with two degrees of freedom per node (Ux, Uy). Use it for a
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
- An old `schema_version` is migrated on load and stamped with the current one
  on the next save.
""",
            "file.save",
            "file.save_as",
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
        ),
        "edit.move": _t(
            "Edit → Move",
            "Edit and tools",
            "Translate the selected nodes in place by (dx, dy, dz).",
            """
Moves the selected nodes, and with them every element that uses them: this is
the transform that changes the model rather than copying it.

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
            "The default tool: click to select, drag to orbit, wheel to zoom.",
            """
Clicking a node or an element selects it; Ctrl+click adds to the selection;
clicking empty space clears it. A box drag selects everything inside it.

With nothing else active this is also what unlocks the model for inspection:
hovering an element shows its properties, and the property dock follows the
selection.
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
- **Grid lines per axis** — each line has an id (the bubble label), an ordinate,
  Primary/Secondary, visibility and a bubble end. The ordinates are what the
  tools snap to.
- Lines are per axis: X lines are planes of constant X, and so on.
- **Working plane** — View → Top (XY), Front (XZ) or Right (YZ) chooses which
  pair of axes is the drawing plane, and the Level combo chooses which level of
  the third axis is active.
""",
            "tools.draw_node",
            "file.new_2d_frame",
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
- **Uniaxial** (used by trusses, zero-length elements and fibre sections):
  `Elastic`, `ElasticPP`, `Hardening`, `Steel01`, `Steel02`, `Concrete01`,
  `Concrete02`, `Concrete04`, `Hysteretic`, `HystereticSM`.
- **nD** (used by plane elements and by `ElasticMembranePlateSection` if you
  prefer a material): `ElasticIsotropic`.
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
        "define.section_library": _t(
            "Define → Section Library",
            "Define",
            "Elastic, fibre, aggregated and plate sections, plus the AISC shapes.",
            """
Sections are what frame, shell and zero-length-section elements point at.

# Types
- **Elastic section** — E, A, Iz, Iy, G, J. What a linear frame analysis needs.
- **Fibre section** — patches and rebar layers tied to uniaxial materials. It
  yields and cracks where the material does, and needs a non-linear case.
- **Section aggregator** — several responses (axial, bending, shear, torsion)
  combined into one section, each with its own material or section.
- **Plate section** (shell) — E, ν, thickness h and density ρ.

# AISC v16 shapes
"Add from AISC…" picks a shape by name (1,660 of them, 13 families). The values
are the published US-customary ones; the dialog shows the published value *and*
the converted one, and E and G remain your choice, because a shape is geometry,
not a material. The data comes from Steel Construction Manual values and was
cross-checked against an independent source before being committed.
""",
            "define.material_library",
            "mechanics.fiber_sections",
            "mechanics.shells",
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
- **Direction** — the DOF driven (1 = X, 2 = Y, 3 = Z).
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
        "assign.support": _t(
            "Assign → Joint → Restraints",
            "Assign — joints",
            "Which degrees of freedom are fixed at the selected nodes.",
            """
A restraint removes a DOF from the unknowns: a fixed DOF carries a reaction
instead of a displacement.

# Values
- **Ux, Uy, Uz** — translations; **Rx, Ry, Rz** — rotations. In a 2D frame model
  only Ux, Uy and Rz exist; in a 2D truss only Ux and Uy.
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
- **DOF numbers** — 1-based, in the order the model uses them: 1 = Ux, 2 = Uy,
  3 = Uz, 4 = Rx, 5 = Ry, 6 = Rz. In a 2D frame model only 1, 2 and 6 exist.
- Ticking 1 and 2 on a pair of nodes at the same level is a diaphragm in plan.

# Mechanics
Tying DOF removes them from the unknowns: the constrained node's displacement is
whatever the retained node's is. It does not add stiffness anywhere else — a
rigid floor is also, physically, a constraint that distributes horizontal force,
which is exactly what this does.
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

# The five types
- **Static** — equilibrium under the patterns' loads, in N steps. See
  **Static analysis**.
- **Modal** — eigenvalues and mode shapes; needs mass. See **Modal analysis**.
- **Pushover** — displacement-controlled monotonic push to a target. See
  **Pushover**.
- **Transient** — time integration of a ground motion or a time series. See
  **Transient analysis**.
- **Response spectrum** — modal maxima combined by SRSS or CQC. See
  **Response spectrum**.

# Options that apply to most types
- **Steps** and, for a transient, **dt**.
- **Numberer, system, algorithm, convergence test** — see Numberer, system and
  solver. The defaults are chosen to work; change them for size or for a case
  that struggles.
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
        ),
        # ──────────────────────────── Display ────────────────────────────
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
            "Node labels, element labels and what the viewport draws.",
            """
Toggles the annotations and the heavy overlays:

- **Node labels** and **element labels** — the name, or `N#`/`E#` when there is
  none.
- **Section extrusions** (View → Show Extruded Sections) — a box swept along each
  member from its section's bounding size, so the physical footprint and the
  local axes are visible.
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
            "Draw each member as a box from its section's size.",
            """
Sweeps each frame element's section bounding box along its axis, semi
transparently. Two things become visible that are hard to see otherwise:

- the **physical footprint** — whether members overlap or fit;
- the **local axes** — the box's orientation is the element's, which is what the
  distributed load components and the diagram signs refer to.
""",
            "display.options",
            "assign.geom_transf",
        ),
        # ──────────────────────────── Options and Help ────────────────────────────
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
    }
)

#: Menu action (attribute name on the main window) → topic.
ACTION_TOPICS: dict[str, str] = {
    # ── File ────────────────────────────────────────────────────────
    "_act_new": "file.new",
    "_act_new_2d": "file.new_2d_frame",
    "_act_new_2d_truss": "file.new_2d_truss",
    "_act_open": "file.open",
    "_act_save": "file.save",
    "_act_save_as": "file.save_as",
    "_act_import_dxf": "file.import_dxf",
    "_act_export_script": "file.export_script",
    "_act_quit": "file.quit",
    # ── Edit and tools ──────────────────────────────────────────────
    "_act_undo": "edit.undo",
    "_act_redo": "edit.redo",
    "_act_delete": "edit.delete",
    "_act_clear_selection": "edit.clear_selection",
    "_act_select_all": "edit.select_all",
    "_act_move": "edit.move",
    "_act_replicate": "edit.replicate",
    "_act_check_duplicates": "edit.check_duplicates",
    "_act_mesh": "edit.mesh",
    "_act_mirror": "edit.mirror",
    "_act_tool_select": "tools.select",
    "_act_tool_draw_node": "tools.draw_node",
    "_act_tool_draw_frame": "tools.draw_frame",
    "_act_tool_draw_truss": "tools.draw_truss",
    # ── Define ──────────────────────────────────────────────────────
    "_act_grid": "define.grid",
    "_act_add_node": "define.add_node",
    "_act_create_shell": "define.create_shell",
    "_act_frame_wizard": "define.portal_frame",
    "_act_material_library": "define.material_library",
    "_act_friction_library": "define.friction_library",
    "_act_material_tester": "define.material_tester",
    "_act_ground_motions": "define.ground_motions",
    "_act_section_library": "define.section_library",
    "_act_add_linear_ts": "define.linear_ts",
    "_act_add_path_ts": "define.path_ts",
    "_act_add_plain_pattern": "define.plain_pattern",
    "_act_add_uniform_excitation": "define.uniform_excitation",
    # ── Assign: joints ──────────────────────────────────────────────
    "_act_assign_support": "assign.support",
    "_act_assign_masses": "assign.masses",
    "_act_assign_equal_dof": "assign.equal_dof",
    "_act_assign_load": "assign.load",
    "_act_assign_zls": "assign.zero_length_section",
    "_act_assign_bearing": "assign.bearing",
    # ── Assign: frame ───────────────────────────────────────────────
    "_act_assign_section": "assign.section",
    "_act_assign_material": "assign.material",
    "_act_assign_geom_transf": "assign.geom_transf",
    "_act_assign_integration": "assign.integration",
    "_act_assign_distributed_load": "assign.distributed_load",
    "_act_assign_hinge": "assign.hinge",
    # ── Analyze ─────────────────────────────────────────────────────
    "_act_case_manager": "analyze.cases",
    "_act_check_model": "analyze.check_model",
    "_act_run": "analyze.run",
    # ── Display ─────────────────────────────────────────────────────
    "_act_show_deformed": "display.deformed",
    "_act_show_mode_shape": "display.mode_shape",
    "_act_show_force_diagram": "display.force_diagram",
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
    # ── Options and Help ────────────────────────────────────────────
    "_act_set_units": "options.units",
    "_act_help_contents": "help.contents",
    "_act_about": "help.about",
}
