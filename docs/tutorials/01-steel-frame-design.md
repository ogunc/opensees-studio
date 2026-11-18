# Tutorial 1 — Designing a steel moment frame (AISC 360-16)

**English** · [Español](01-steel-frame-design.es.md)

You will open a two-bay, two-storey steel frame, run its load cases, check every
member against AISC 360-16 and the storey drifts against ASCE 7, and see how the
lateral bracing of the beams decides whether the roof beams pass.

**You need:** OpenSees Studio with a solver (Options → Solver) and the example
`examples/steel_frame_design.osmodel` (or run `python examples/steel_frame_design.py`
to rebuild it).

## 1. The model

File → **Open…** → `examples/steel_frame_design.osmodel`.

It is a 2D frame in the X-Z plane: bays of 6 m, storeys of 4 m, fixed bases.

| Members | Section | Notes |
|---|---|---|
| Columns | `W10X49` | from Define → Section Library |
| Beams | `W16X31` | braced at thirds of the span by the floor joists |

The sections were taken from **Define → Section Library** (AISC v16). They keep
the shape's name (`W10X49`), and that name is how the steel check knows which
shape to design with. A section you typed yourself can still be checked: name the
shape for its members in the check's overrides (step 4).

Loads, in **Define → Add Plain Load Pattern…** and the model tree:

- **DEAD**: self weight (the sections carry a unit weight of 77 kN/m³) plus
  25 kN/m on the beams.
- **LIVE**: 20 kN/m on the beams.
- **WIND**: 60 kN and 40 kN at the first and second floor.

and three combinations in **Define → Load Combinations…**: `1.4D`,
`1.2D+1.6L` and `1.2D+1.0W+L`.

## 2. Run the cases

**Analyze → Run All Cases**. Each static case runs once; the combinations are
evaluated from those results whenever they are needed, so they never run
themselves.

## 3. Check the members

**Design → Steel Frame Check (AISC 360-16)…**

![The steel frame check after Check](img/steel-check.png)

- **Method** LRFD, **Fy** 345 MPa (50 ksi), **ratio limit** 1.0. These were saved
  with the example; a new project starts from 50 ksi in its own units.
- The list on the right is what is enveloped: every **combination** is ticked by
  default. Tick a case to check it on its own. A case without a result says
  "no result: run it first".
- Press **Check**. One row per member, the largest ratio first: the governing
  check (here the **P-M interaction**, H1-1a or H1-1b), the equation and the load
  set that produced it.

The roof beams (elements 9 and 10) are at 0.97 and 0.94: the combination with
wind and the gravity combination respectively. They pass because their
compression flange is braced every 2 m, which the example stores as an override
(`Lb = 2 m`).

> **How the demands are read.** Each member is sampled at 25 stations, span
> loads included, and the largest axial force, moments and shears are taken
> together, which is conservative for the interaction. Cb comes from the
> member's own moment diagram (F1-1) unless you set it — set **Cb = 1.0 for a
> cantilever**.

## 4. What if the beams were not braced?

1. Close the dialog with **Cancel** and select the four beams (click them, or
   Select → By Section → W16X31).
2. Open the check again. The **Overrides for the 4 selected member(s)** box is
   now active.
3. Set **Lb (LTB) = 0** (the member length, 6 m) and press **Apply to the selected
   members**, then **Check**.

Lateral-torsional buckling over 6 m — beyond Lr, so the elastic F2-3 — now cuts
the beams' flexural strength: all four go to 1.2–1.4 and their rows turn red. **Select failing members** closes the dialog with them
selected, ready for Assign → Frame → Section… to give them a deeper shape. Press
**OK** to keep the overrides in the project, or **Cancel** to forget them.

The other overrides: the AISC **shape** to check with, **K** about each axis (the
buckling lengths are the member length times K), and **Cb**.

**Show ratios on the model** closes the dialog and paints every member by its
ratio: blue below 0.5, then teal, green and orange up to the limit, red above
it, grey when not designed. Design → Display Steel Ratios on Model does the same
from the menu with the saved settings, and Display → Back to Model removes the
colours. File → Export → Report prints the same table.

## 5. Check the storey drifts

**Design → Storey Drift Check…**

![The storey drift check with the ASCE 7 preset](img/drift-check.png)

- **Code** → *ASCE 7-22, Risk Category I/II (0.020 h)*.
- **Amplification** → 5.5, the Cd / Ie of a special steel moment frame: the
  analysis gives elastic drifts, ASCE 7 limits the amplified ones.
- **Check**: every static case with a result, storey by storey. WIND is the one
  that matters; the gravity cases sway almost nothing.

The storeys come from the Z grid lines (Define → Storeys…). A model without
storeys has nothing to check, and the dialog says so.

## 6. Save

**File → Save**. The design settings — method, Fy, the load sets, the member
overrides and the drift limit — are saved in the project. They do not change
any analysis result, so editing them never asks you to run again.

## What the check covers, and what it does not

AISC 360-16 for **W, M, S and HP** shapes: tension yielding (rupture needs the
net area), compression (E3, E4, E7), flexure (F2, F3, F6), shear (G2.1, G6) and
H1. Channels (F2, E4), tees (F9), equal-leg angles (F10), rectangular HSS (F7,
G4) and round HSS and pipes (F8, G5) are checked by the same dialog. Unequal-leg
angles and double angles are listed as not designed, and so is a member whose
section has no AISC name and no override. Set **Fy** for the material: A500
Grade C HSS is 50 ksi (46 ksi round), A53 pipe 35 ksi. The numbers are checked
against the AISC Design Examples in the
[Verification Manual](../verification-manual.md) (cases D-01 to D-05).
