# CLAUDE.md — Project context for Claude Code

This file is loaded automatically by Claude Code (and other AI coding
assistants) when working in this repo. It captures the architectural
rules, conventions, and gotchas that aren't obvious from reading the
code. Keep it short — link out instead of duplicating.

## Project: OpenSees Studio

A SAP2000-style desktop GUI for OpenSeesPy. PySide6 + PyVista + pyqtgraph.

See [`README.md`](README.md) for the user-facing overview and
[`docs/architecture.md`](docs/architecture.md) for the long form
architecture document.

## Architecture

- **Pattern**: MVVM + service layer.
- **`core/`** — pure Python, no Qt, no openseespy. Pydantic v2 models for
  `Project`, `Node`, `Element`, `Material`, `Section`, `Load`, `Analysis`.
  Safe to import from a script, notebook, or future CLI.
- **`services/`** — `OpenSeesRunner`, persistence, deformation, spectrum,
  section_properties, animation_export. May import openseespy. No Qt.
- **`viewmodels/`** — Qt-aware adapters. `ProjectViewModel`,
  `AnalysisRunner`, `QUndoStack`.
- **`views/`** — Qt widgets, dialogs, 3D canvas. Never imports
  openseespy directly — go through a service.
- **`commands/`** — `QUndoCommand` subclasses for every model mutation.
- **Analysis execution** runs in a child process. `AnalysisRunner`
  (viewmodels) first writes the pre-run snapshot
  `<stem>.run-snapshot.osmodel` next to the project file (for a never-saved
  project `untitled.run-snapshot.osmodel` in the app data directory,
  override with `OPENSEES_STUDIO_DATA_DIR`), then starts
  `python -u -m opensees_studio.run --project <snapshot> --cases <id> --out <dir>`
  with `QProcess` (`sys.executable`, unbuffered so the stderr of a hard exit
  is not lost). The CLI (`opensees_studio/run.py`) prints
  one JSON object per stdout line (`log`, `progress`, `case_started`,
  `case_finished`, `error`), flushed per line; fd 1 is redirected to stderr
  first, so OpenSees native output never touches the protocol. Exit codes:
  0 every case ran (an early stop is a result), 2 Python-side analysis
  error with an `error` line, 3 invalid project or reference; anything else
  means the child died. Results travel through `services/result_store.py`
  (float64 HDF5 plus `manifest.json`, lossless) and are rebuilt with
  `load_results`. The snapshot doubles as crash recovery: on open, a
  snapshot newer than the file prompts to restore or discard; a normal save,
  a close, or New/Open replacing the project removes it
  (`ProjectViewModel._retire_run_snapshot`, only once the replacement has
  happened). `OPENSEES_STUDIO_IN_PROCESS=1` runs the previous
  threaded in-process worker (debugging, no cancel).
  Batch runs (File → Run Batch…, `python -m opensees_studio.batch`, `--batch`
  in a frozen bundle) start the same CLI per project file with `--out
  <stem>_batch_results --record-db <stem>_results.sqlite`; `services/batch.py`
  plans jobs and writes `batch.json` (the model fingerprint), and File → Open
  offers those results only while `model_fingerprint` still matches.
  `OPENSEES_STUDIO_CLI_HARD_EXIT_AFTER=N` is a test-only hook that makes the
  CLI hard-exit with 255 after N progress lines.
  `OPENSEES_STUDIO_TEST_SKIP_BEARING_ORIENT=1` is a test-only hook that leaves
  `-orient` off bearings, so OpenSees itself hard-exits on a zero-length
  bearing. Solver-speed banners (the fullGenLapack "VERY SLOW" line) are kept
  out of the run log and stay in the stderr capture. The Material Tester still
  calls OpenSees in the GUI process.

The dependency direction is strict and one-way: `views → commands →
viewmodels → services → core`, and CI enforces it with import-linter
(`[tool.importlinter]` in `pyproject.toml`, run as `lint-imports`): the
layers, plus "core imports no Qt and no OpenSeesPy", "services import no Qt
except `services/qt_workers.py`", and "nobody outside `services/` imports
OpenSeesPy directly". Run it before pushing; a violation fails the `test`
job.

## Tech stack

- **Python 3.12** (`requires-python = ">=3.12"`), PySide6 (Qt 6), PyVista/VTK,
  pyqtgraph, OpenSeesPy 3.8.0.0, Pydantic v2, h5py, imageio[ffmpeg], ifcopenshell
  (File → Export → IFC; imported only inside `services/ifc_export.py` when it
  runs, so headless installs never need it).
- Why 3.12: the `openseespywin` and `openseespylinux` 3.8.0.0 wheels both
  declare `Requires-Python >=3.12`. On Windows the wheel ships a single
  `opensees.pyd` linked against `python312.dll`, so use 3.12 exactly (3.13
  cannot load it, even though pip will install it).
- Windows DLL fix: pin `openseespy==3.8.0.0` *and* `openseespywin==3.8.0.0`.

### Venv layout (Windows dev machine, as of 2026-09-18)

- `.venv/`: the live environment. Python 3.12.10, OpenSeesPy 3.8.0.0,
  created with `py -3.12 -m venv .venv` then `pip install -e ".[gui,dev]"`.
- `.venv/` is the only interpreter inside the repo. The py311 rollback
  environment (`.venv-old-py311/`) and the stale Python 3.9.1 `venv/` were
  deleted on 2026-09-18 once the lock file below was recorded.

### Reproducing the known-good environment

`requirements-lock.txt` is a `pip freeze --exclude-editable` of the live
`.venv` (Python 3.12.10 + OpenSeesPy 3.8.0.0), recorded after unit 299,
integration 55 and GUI 181 passed on it. It is a record, not a constraint
file: `pyproject.toml` stays the source of truth for dependency ranges. To
rebuild that exact state: `py -3.12 -m venv .venv`, then
`pip install -r requirements-lock.txt`, then `pip install -e . --no-deps`.
Regenerate the file only after all three suites pass on a changed environment.

## Conventions and gotchas

These are non-obvious things that are easy to break if you don't know:

- Z is the elevation axis of every model. A 2D model lives in the global
  **X-Z plane** (nodes at y = 0) with DOFs Ux, Uz, Ry in storage slots 0, 2, 4;
  OpenSees gets (X, Z) as its (x, y). Everything crossing that boundary goes
  through `core.plane`: `dof_indices`/`dof_signs` (a 2D rotation or moment is
  `-1` times the OpenSees value), `to_solver_coords`, `to_solver_vector3`. Never
  slice `coords[:ndm]` for OpenSees, and never assume 2D means "Y up". Result
  arrays keep OpenSees' DOF order with the global sign applied. 2D files below
  schema 3 are rotated on load by `migrate_2d_payload_to_xz`.
- `ForceComponent` is a plain `Enum`, **not** a `str`-Enum — a `str`
  mix-in breaks `.value` lookup inside PyVista renderers.
- `QObject.receivers()` in PySide6 takes a SIGNAL string, not a
  `SignalInstance` — avoid it.
- Qt mouse-event positions are LOGICAL pixels; VTK is DEVICE pixels.
  Scale by `widget.devicePixelRatioF()` when picking.
- `ModalResults.mode_shapes` is **1-indexed** (mode 1 → key `1`).
- `PathTimeSeries` field is `dt`, not `time_step`.
- `DiagramRenderer` must early-return when `abs_max == 0` — avoid
  divide-by-zero in the colour scale.
- The end-`j` sign is flipped in `extract_diagram_data` so axial /
  shear / moment diagrams are continuous across an element.
- `ProjectCommand` holds its view model by weak reference. Never store a
  strong reference to the view model (or anything owning its `QUndoStack`)
  on a command: the cycle through the stack corrupts the heap when the GC
  frees many of them (`0xC0000374`).
- Floating-point inputs use `views.float_field.FloatField` (full double,
  scientific notation, shortest round-trip display); do not add a plain
  `QDoubleSpinBox`, it rounds to its decimals.
- Unsaved-changes prompt. `MainWindow.closeEvent` confirms only a
  *user-initiated* close: one the window manager sent (`event.spontaneous()`)
  or `File → Quit`, which goes through `_on_quit`. A programmatic `close()`
  (test teardown, `closeAllWindows()` while shutting down) never prompts — a
  modal dialog with no event loop running wedges the exit. `_on_save` and
  `_on_save_as` return `True` when the file was written, and
  `_confirm_discard_changes(action)` is the one prompt shared by close, New
  and Open so the three cannot drift apart.
- Draw tools need something to snap to. `MainWindow._require_drawable_grid`
  offers Define → Coordinate System/Grids… when the project has no visible
  grid lines: the canvas rejects every off-grid click, so a fresh project
  with an empty Global grid looks broken rather than empty.
- `services.persistence._write_text_atomic` is the only way a project or a
  snapshot reaches disk; a save must never truncate the file the user
  already has. `load_project` refuses a `schema_version` newer than
  `SCHEMA_VERSION` instead of quietly rewriting it one version down.
- An unregistered material type is not a crash: `material_forms.form_for`
  returns a read-only placeholder, the same contract `section_forms` has.
- Never hardcode how the analysis child is spawned. Both spawn sites
  (`viewmodels/analysis_runner.py` and the eigen re-exec in `run.py`) build
  their argv from `child_cli.analysis_cli_command()`: a source install
  re-enters through `python -u -m opensees_studio.run`, a frozen bundle
  through its own executable plus `child_cli.CLI_FLAG`, which `__main__`
  dispatches back to `run.main`. A hardcoded `sys.executable -m ...` works
  in development and breaks every packaged build.
- An option added to an existing model keeps old files byte-identical by
  leaving its default out of the dump: `core._base.omit_when_default`
  (used by the beam integration rule and the numberer).
- `ops.wipe()` does not reset OpenSees' class-static scratch. `truss` shares
  its force vector and stiffness matrix between 3D ndf 3 and 2D ndf 3 and in
  2D never writes the rotation rows, so `OpenSeesRunner.build` clears them
  (`_clear_truss_scratch`) before a 2D ndf 3 model with trusses. Suspect the
  same when a result depends on what ran earlier in the process.
- `Entity.id` is `PositiveInt` (>0). The sentinel `999999` is reserved
  for in-flight / temporary objects that haven't been assigned a real id.
- Eigen determinism rule. ARPACK keeps its random start vector across
  `ops.eigen` calls, so only the first ARPACK eigen call of a process is
  reproducible: a second call flips mode signs and rotates a repeated
  eigenvalue pair. Never pick an eigen solver by hand: take it from
  `core.modal.resolve_modal_solver` (dense `fullGenLapack` at or below
  `DENSE_EIGEN_MAX_FREE_DOF` = 500 free DOF, override with
  `OPENSEES_STUDIO_DENSE_EIGEN_MAX_DOF`, ARPACK above), and never add a
  second ARPACK eigen call to a process: the CLI (`run.py`) re-executes
  such a case in a fresh child, so new eigen-using case types must be
  listed in its `_uses_eigen` and `_routed_to_arpack`. Every mode shape
  that reaches display or combination must pass
  `orthogonalize_degenerate_modes` (repeated eigenvalues: the dense
  solver returns a mass-oblique pair) and `normalize_mode_sign` (tie
  tolerance 1e-9, lowest DOF index wins), as `_run_modal` does; record the
  solver used in the results. Combination rules live in
  `core.modal_combination`; new response spectrum cases default to CQC.
  Response spectrum reactions, element forces and shell resultants are the
  static response to each mode's equivalent load `M φ Γ Sa`
  (`services.spectrum.modal_equivalent_loads`, solved in
  `OpenSeesRunner._modal_static_responses` after the one eigen call, never a
  second `ops.eigen`), combined per component by
  `core.modal_combination.combine_modal_fields` with the same rule and ρ as the
  displacements. They are peak magnitudes; `services.combination.case_bounds`
  turns them into ±peak. The load uses nodal mass only (as the participation
  factors do), not element density.
- **No SAP2000-generated file enters the repository.** The `.s2k` files in
  `tests/fixtures/s2k` are hand-written from the table format, and a test builds
  its own text inline. A real export is used locally only, to check a table's
  columns and fields, and is never copied in: the clean-room provenance of
  `services/sap2000_text.py` depends on it.

## Dependency split

`pyproject.toml` separates dependencies into two tiers:

- **Base** (`pip install -e .`): `pydantic`, `numpy`, `h5py`, `ezdxf`. No
  solver: it models, exports and reports. Safe to use headlessly — no Qt, no
  PyVista, no VTK.
- **Solver extra** (`pip install -e ".[opensees]"`): `openseespy` (and
  `openseespywin` on Windows). OpenSeesPy is an optional *engine* with its own
  license, never a base dependency: `services/engines.py` finds it (this
  environment, another Python 3.12, or a folder appended to `sys.path`, saved in
  `solver.json`), the analysis child gets the folder in
  `OPENSEES_STUDIO_ENGINE_PATH` and the chosen engine in
  `OPENSEES_STUDIO_ENGINE` (it builds that engine's runner with
  `create_runner` and refuses case types the engine does not declare), and the
  GUI disables Run without an engine, and Check Stability and the Material
  Tester without OpenSeesPy (they always call OpenSees). Never import OpenSeesPy at module level, and
  never detect it by importing it. See `docs/adr/ADR-0003-solver-engines.md`.
  Scripts and web backends that solve install `.[opensees]`.
- **GUI extra** (`pip install -e ".[gui]"`): adds PySide6, pyvista, pyvistaqt,
  vtk, pyqtgraph, imageio, ifcopenshell, and `PyNiteFEA` — the bundled second
  engine (MIT; `services/pynite_runner.py`, linear static and P-Delta of elastic
  frames and trusses, results in OpenSees' layout and tested against it in
  `tests/integration/test_pynite_parity.py`). Required to launch the desktop app.

Desktop dev: `pip install -e ".[gui,dev]"` (`dev` pulls in `opensees`).
Web / headless: `pip install -e .` (then verify with
`python -c "import sys, opensees_studio.core; assert 'PySide6' not in sys.modules"`).

See `docs/adr/ADR-0002-headless-gui-dep-split.md` for the rationale.

### Frozen builds

`packaging/` freezes the app into a folder an end user runs without Python
(`pip install -e ".[gui,packaging]"`, then `python packaging/build.py`). The
bundle **excludes OpenSeesPy** (ADR-0003): the user installs it from Options →
Solver (`services/engine_install.py`, pinned PyPI wheels with SHA256), and the
smoke test proves both that the frozen CLI refuses without it and that it
solves once installed. The GUI never solves in its own process, so the bundle
re-enters itself as the analysis CLI — see the child-spawn gotcha above. Build with **Python 3.12**:
the interpreter inside the bundle has to be the one the Windows
`opensees.pyd` links against. `packaging/README.md` documents the traps
(the `vtk` shim, PyVista's mypyc module, why VTK is not trimmed); the smoke
test in `build.py` is what proves a bundle can solve before it is shipped.

## Running

```bash
# Activate the venv
.venv\Scripts\activate         # Windows
source .venv/bin/activate      # Linux/macOS

# Launch the app
python -m opensees_studio

# Run tests
pytest tests/unit -v           # pure-logic, no Qt, no openseespy
pytest tests/gui -v            # pytest-qt, real Qt event loop
pytest tests/integration -v    # real openseespy runs (slow)
```

## Test structure

- `tests/unit/` — pure logic, instant. No Qt, no openseespy.
  It runs without any `QT_QPA_PLATFORM` setting; a test that needs `qtbot`
  (and with it a QApplication) belongs in `tests/gui/`.
- `tests/gui/` — `qtbot` fixture, `@pytest.mark.gui`.
  Run it in one pytest process: `pytest tests/gui` (255 tests in 45 files
  as of 2026-09-28, about 50 s on Windows). CI does the same in its `gui`
  job. Check the exit code, not only the pass count: any non-zero code (for
  example `0xC0000374` after all tests pass) is a teardown bug.
  `tests/gui/conftest.py` closes plotters and top-level widgets at session
  end. Fallback for diagnosing a crash: run one process per test file, which
  names the failing file (about 185 s on Windows):
  `Get-ChildItem tests\gui\test_*.py | ForEach-Object { python -m pytest $_.FullName }`.
  The single process used to segfault around test 73 because VTK render
  windows accumulated (see `reports/STATUS_2026-09-12.md`); since the
  2026-09-23 teardown fixes it passes.
- `tests/integration/` — real `openseespy` runs that exercise full
  model → solve → results pipelines on the bundled examples, including the
  analysis CLI as a subprocess (`test_analysis_cli.py`) and the
  direct-versus-CLI result parity (`test_cli_result_parity.py`).

## Render budget

`tools/render_bench.py` builds synthetic models and measures the geometry build
(CPU) and the number of actors from the renderer, without opening a GPU context
— `tests/tools/test_render_budget.py` runs it in the normal suite. The ceilings
live in `tools/render-budget.txt` and are a ratchet: the actor count is exact,
the time ceiling is wide enough to survive a busy runner. Target from the
roadmap: 10k nodes and 20k frames at 30 fps, so the numbers only go down.

## Examples

The `examples/` directory contains both Python scripts and
pre-generated `.osmodel` files. Each script builds the project, saves
it, reloads, and round-trips for sanity. See [`examples/README.md`](examples/README.md)
for the full catalogue.

To regenerate every example after changing the data model:

```bash
for f in examples/*.py; do python "$f"; done
```

## Before opening a PR

A PR is not ready until the documentation that the change invalidates is
fixed **in the same PR**. This applies to every PR, not only to
user-visible features:

1. **Help pages.** Every menu action and dialog has a page in
   `core/help.py`. Add the new ones to `TOPICS` **and** to
   `ACTION_TOPICS`; `tests/gui/test_help_window.py::test_every_menu_action_declares_a_page_that_exists`
   fails on an action that does not declare one. Write the body for
   somebody who has the dialog open, and link related pages through
   `see_also`.
2. **User-facing docs.** `README.md`, `docs/` and `examples/README.md`
   wherever the change alters what they describe: menu paths, shortcuts,
   file format, command line, I/O.
3. **Format and behaviour changes.** If the `.osmodel` payload gained a
   field, document it where the format is described and keep the
   `omit_when_default` rule (a project that does not use the option must
   still save byte-identical).
4. **Delete what is no longer true.** A stale paragraph, a screenshot of a
   removed dialog, a documented flag that no longer exists: remove it in
   the same PR instead of leaving the contradiction in place.
5. **CHANGELOG.** Add the entry when the change is user-visible.
6. **Gates.** `ruff check`, `ruff format --check`, `python tools/typecheck.py`
   (must stay within the budget) and `lint-imports` before pushing.

## Branch strategy

- `main` is the only integration branch in this fork: a short-lived branch per
  change (`feat/`, `fix/`, `chore/`, …) merged by pull request.
- For contributions to the original repository, branch from `upstream/main`;
  its `develop` branch is the maintainer's experimental branch, not a PR target.
- Releases are tags on `main` (`v0.0.x`). **Pushing the tag is what publishes**:
  `desktop.yml` builds the three bundles, writes `SHA256SUMS.txt` and the
  `publish` job creates the release with the notes taken from `CHANGELOG.md`.
  Do not write the release body by hand — the workflow overwrites it.
- Conventional commit style: `feat:`, `fix:`, `refactor:`, `docs:`,
  `test:`, `chore:`, `ci:`.
