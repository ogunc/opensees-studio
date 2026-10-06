# Owner's manual checks

Use a disposable copy of a model and save exports to a chosen work folder.
Numeric input and CSV files use a decimal point. Run these checks on the owner
desktop; automated validation does not replace the visual checks below.

1. **2D mass components.** File > New 2D Frame; Define > Add Node; select the
   node; Assign > Joint > Masses. Expected: Ux, Uy and Rz fields. Enter distinct
   values and reopen the dialog or inspect Properties; Rz maps to rotational mass.
2. **Unfocused wheel.** Analyze > Cases; move the pointer over an unfocused
   Numberer, System or Constraints combo and turn the wheel. Expected: the value
   stays unchanged; a scrollable form scrolls. Focus the combo before changing it.
3. **Dirty New prompt.** Edit a node, then File > New 2D Frame. Expected:
   Save/Discard/Cancel prompt. Cancel keeps the model and unsaved indicator;
   Save writes it; Discard replaces it. Canceling Save As also keeps the model.
4. **Dirty Open prompt.** Edit a node, then File > Open. Expected: the same
   three choices; canceling either dialog preserves the current project.
5. **Results after New.** Analyze > Run (F5) on example 01, then File > New 2D
   Frame. Expected: Results says no results yet, its tables and plot are empty,
   and result display actions cannot show the previous project's solution.
6. **Invalid analysis case.** Analyze > Cases: select a pattern-based case with
   no valid pattern selected, then Apply changes. Expected: an inline refusal
   explains the invalid reference. Analyze > Run refuses an invalid saved case
   and names that case; no stale result appears as a successful new run.
7. **Save state and recovery.** File > Save As to a disposable file; edit a node.
   Expected: Saved changes to Unsaved changes and the title gains its dirty mark.
   File > Recovery interval: choose 1 minute, wait at least one minute while
   dirty, and expect the recovery snapshot status. Reopening the saved file
   offers its newer recovery data. Restore it, then Save; the clean state returns.
8. **Constant time series.** Define > Time Series > Constant: add a named series
   with factor 1, apply a change, undo and redo. Define > Add Plain Load Pattern:
   select it. Expected: the Constant series persists after save/reopen and is
   available to the load pattern. Example 04 uses it for axial preload.
9. **ModifiedNewton initial tangent.** Open example 06; Analyze > Cases > ModifiedNewton initial.
   Expected: ModifiedNewton with Initial tangent selected. Apply, save, reopen
   and run; the selection persists and the pushover completes.
10. **Preload cases.** In example 06, Analyze > Cases > ModifiedNewton initial: inspect Preload
    cases. Expected: Gravity is selected before lateral loading. The pushover
    starts from the gravity-deformed state and ends at Ux = 15.1 at node 3.
11. **Static history plot and CSV.** Open example 02; Analyze > Run > Load history.
    Results > Static curve: select node 4 Ux. Expected: a nonlinear load versus
    displacement curve. Results > Static history > Export CSV: 1001 data rows,
    including the initial point, load factor and displacement columns.
12. **Result precision and export.** Analyze > Run on example 01. Results >
    Significant digits: change 6 to 15. Expected: displayed values gain digits.
    Export the same tab at both settings using Export CSV. The CSV files are
    identical and retain full precision with units in the header.
13. **Geometric transformation.** Open example 05; select a column; Assign >
    Frame > Geometric Transformation. Expected: PDelta can be assigned, undone,
    saved and reopened. The columns in the supplied model already use PDelta.
14. **Beam integration.** Open example 07; select a frame element; Assign > Frame
    > Beam Integration. Expected: Lobatto with 4 points; Apply, Undo and Redo
    preserve the selected rule and point count in Properties and after reopening.
15. **W-shape template.** Define > Section Library > New Fiber. Select the
    W-shape template, material 1, d = 10.5, bf = 5.77, tf = 0.44, tw = 0.26,
    web fibres = 15, flange fibres = 16; click Add W-shape. Expected: three
    patches and 47 fibers, area 7.5788. The 2D fibers lie along z = 0; the preview
    is a discretized section axis. Retain the example's inch/kip numbers even
    where the current generic preview still displays SI labels.
16. **Decorated window fits.** Open the application on each available display,
    then close/reopen it and open Analyze > Cases and the Fiber Section Editor.
    Expected: the whole frame, including title bar and borders, stays within the
    screen's available area. Repeat on a smaller display or after changing scale.
17. **Official 01.** File > Open > examples/official/01_elastic_truss.osmodel;
    Analyze > Run > Linear static. Expected: successful one-step solution,
    displacement/reaction tables, and no early-stop warning.
18. **Official 02.** File > Open > examples/official/02_nonlinear_truss.osmodel;
    Analyze > Run > Load history. Expected: 1000 successful increments,
    Hardening material, 1001-point static history and CSV.
19. **Official 03.** File > Open > examples/official/03_portal_frame_2d.osmodel;
    Analyze > Run: select Seven modes and Linear static. Expected: seven finite
    periods and a successful static result. Inspect each case in the run results.
20. **Official 04.** File > Open > examples/official/04_moment_curvature.osmodel;
    Analyze > Run: select both cases. Expected: Constant axial preload followed
    by 100 curvature increments. Display > Show Pushover Curve shows the moment
    versus curvature response. The reference adds the undeformed point to the
    101 solver snapshots for 102 comparison points.
21. **Official 05.** File > Open > examples/official/05_rc_frame_gravity.osmodel;
    Analyze > Run > Gravity. Expected: 10 successful increments, downward beam
    displacement and balancing support reactions.
22. **Official 06.** File > Open > examples/official/06_rc_frame_pushover.osmodel;
    Analyze > Run: select Gravity and ModifiedNewton initial. Expected: both complete, including
    151 lateral increments; the reference has 161 gravity/lateral curve points.
23. **Official 07.** File > Open > examples/official/07_three_story_steel.osmodel;
    Analyze > Run: select Gravity and Pushover. Expected: 10 gravity and 180
    lateral increments, final roof Ux about 18, and a 181-point pushover curve.
    Inspect Steel02 isotropic parameters and the five W-shape template sections.
24. **Reopen and rerun.** For each official model above, File > Save As to the
    work folder, File > Open that saved file, then Analyze > Run the same cases.
    Expected: the same results and identical CSV exports. The automated tests
    additionally compare all stored reference scalars and curve points.

The screenshot walkthroughs are generated locally with
`python tools/capture_example_steps.py NN --out E:/osv-docs/structural/NN`.
Each folder contains PNGs and `steps.md` with the actual dialog inputs.
