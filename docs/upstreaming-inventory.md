# Upstreaming inventory

Status: **reconciliation branch, not a pull request to the original repository yet.**

- Fork: `marcel1983/opensees-studio`
- Original: `ogunc/opensees-studio`
- Upstream remote: `upstream`
- Fork baseline before this sync: `9bb7a1c` (`v0.0.29`)
- Upstream baseline merged: `907dc6f` (`Merge pull request #11 ...`)
- Common ancestor: `76f69fb`
- Reconciliation branch: `sync/upstream-main`

The fork is **284 commits ahead** of the common ancestor; the original is
**24 commits ahead**. A single PR from `fork/main` to `upstream/main` would be
about **500 files and 80 000 added lines**, and is not a reviewable unit.

## What this branch does

1. Merges `upstream/main` into the fork so the fork no longer carries an old
   copy of the original's work.
2. Preserves both sides in the seven conflicting files:
   `CHANGELOG.md`, `CLAUDE.md`, `core/help.py`,
   `services/opensees_runner.py`, `views/dialogs/case_forms.py`,
   `views/dialogs/case_manager.py` and `views/main_window.py`. The original's
   new `core/model_check.py` is kept and adapted to the fork.
3. Keeps the original's newer features:
   - **Analyze → Check Model (F6)** and the pre-run review.
   - **Constant Time Series**.
   - Newton/ModifiedNewton `-initial` algorithm arguments.
   - Preload cases for pushover and transient.
   - The CI/typecheck hardening and macOS GUI timeout fixes.
4. Keeps the fork's features, including the numerical stability check,
   the X-Z 2D convention, S2K import, viewer work, reports and examples.
5. Makes the merged model check understand the fork:
   - X-Z 2D models as well as the original's X-Y 2D convention.
   - Rigid links, rigid diaphragms and floating diaphragm master nodes.
6. Keeps `algorithm_args` in the saved analysis cases, and improves the
   pre-run dialog integration and mass-emitter test compatibility.
7. Adapts two original tests to the fork's 2D convention: the mass dialog
   labels/mass component and the zeroLength rotational spring slot. The
   originals remain valid for an X-Y upstream branch; this branch documents the
   conversion instead of pretending both conventions are identical.

### Validation of this branch

- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `lint-imports`: 4 contracts kept, 0 broken.
- `pytest tests/unit tests/integration tests/tools`: passed (skips are the
  optional `PyNite`, `ifcopenshell`, `imageio_ffmpeg`, PORTICO and gidopensees
  checkouts; one known RC-frame xfail).
- `pytest tests/gui`: passed.
- Local `tools/typecheck.py`: 198 errors against the 189 budget with the local
  mypy 2.4.0; CI installs the locked mypy 2.3.1. The touched core modules pass
  mypy. Do not raise the budget to hide this drift.

## Rules of the original repository

From `ogunc/opensees-studio/CONTRIBUTING.md`:

- PRs target **`main`**. `develop` is the maintainer's experimental branch.
- Start every PR from an up-to-date `upstream/main`.
- **One pull request does one thing**; mention dependencies between PRs.
- Conventional Commits.
- Run the gates listed above before asking for review.
- Keep the mypy ratchet: the budget may only go down.

## Proposed PR units

These are review units, not a promise that every one will be accepted. Source
PR numbers refer to the fork's merged PRs. Split any row further if the diff
is still too broad for review.

| ID | Proposed branch / title | Source in fork | Depends on | Risk |
|---|---|---|---|---|
| CI-1 | `ci: harden the typecheck and GUI jobs` | #16, #31, #41, #55; dependabot; `tools/typecheck.py` | — | Low |
| AXIS-1 | `feat(axes)!: Z is the elevation axis of 2D models` | #11 | Maintainer decision | **High / breaking** |
| FIX-1 | `fix(runner): element loads, missing loads and reaction state` | #1, #6, #7, #58, #61 | — | Low |
| MODEL-1 | `feat(frames): offsets, releases, shear areas and AISC axes` | #1, #7 | — | Medium |
| MODEL-2 | `feat(buildings): storeys, diaphragms and mass source` | #2, #4, #5 | AXIS-1 for 2D consistency | Medium |
| MODEL-3 | `feat(supports): elastic springs per DOF` | #24 | — | Low |
| MODEL-4 | `feat(groups,tables): groups, section cuts and editable tables` | #20, #21, #22 | MODEL-1 | Medium |
| MODEL-5 | `feat(materials): RC walls, ConcreteCM and validated gap/damper materials` | #67 | — | Medium |
| LOAD-1 | `feat(loads): surface, floor, seismic, temperature and settlement loads` | #17, #18, #51, #65, #77 | MODEL-1/2 | Medium |
| ANALYSIS-1 | `feat(analysis): solver options, modal damping and result databases` | #25, #27, #34, #38, #52, #59, #60 | — | Medium |
| ANALYSIS-2 | `feat(analysis): batch analysis of many projects` | #69 | ANALYSIS-1 | Medium |
| RESULTS-1 | `feat(results): reports, IFC, influence lines and section cuts` | #19, #23, #34, #36, #56 | MODEL-4 | Medium |
| GRID-1 | `feat(grids): radial grids, wizard, labels and grid-line view` | #29 | — | Low |
| VIEW-1 | `feat(view): multiple viewports, visibility and hiding` | #32, #93 | — | Low–medium |
| VIEW-2 | `feat(view): rotate, color-by and real section extrusion` | #63, #64, #66 | VIEW-1 | Medium |
| VIEW-3 | `perf(viewer): batched actors, markers and cached lookups` | #42–#48, #83, #85 | VIEW-1 | Medium |
| VIEW-4 | `feat(viewer): screen-relative markers and release points` | #84, #86 | VIEW-3 | Low |
| EDIT-1 | `feat(edit): move, replicate, mirror and delete loads` | #49, #65 | — | Low |
| S2K-1 | `feat(s2k): import/export the baseline SAP2000 text format` | #70, #72 | MODEL-1 | High |
| S2K-2 | `feat(s2k): joint masses, springs and real-world sections` | #73, #74 | S2K-1 | High |
| S2K-3 | `feat(s2k): modal and response-spectrum cases` | #75, #76 | S2K-1 | Medium |
| S2K-4 | `feat(s2k): temperature, settlements, added mass and preloads` | #77 | S2K-1, LOAD-1 | High |
| S2K-5 | `feat(s2k): nonprismatic sections, modifiers and diaphragms` | #78, #79, #80 | S2K-2, MODEL-2 | High |
| S2K-6 | `docs(s2k): import status and limitations` | #81 | S2K-1..5 | Low |
| STABILITY-1 | `feat(analyze): scalable numerical stability check` | #12, #13, #87, #89, #91 | AXIS-1 decision; upstream Check Model | **High / design** |
| DOCS-1 | `docs: verification manual, tutorials and examples` | docs/examples work | Features they describe | Low |
| RELEASE-1 | Fork releases and bundles | #9, #15, #26, … #94 | — | **Not for upstream** |

### First wave

Recommended order:

1. **CI-1** — it is small and makes every later PR easier to judge.
2. **FIX-1** — independent runner fixes with regression tests.
3. **VIEW-1** — the newly finished isolate/visible-only selection work; it is
   self-contained and already has GUI coverage.
4. **VIEW-4** — screen-relative markers and release points, if the maintainer
   wants the viewer work.
5. **GRID-1** and **EDIT-1** — isolated UI features.

Leave **AXIS-1**, **S2K-*** and **STABILITY-1** for an explicit design
conversation. They change conventions, schema or analysis behavior, and a
large surprise PR in those areas is likely to stall.

### Execution status (2026-10-26)

The upstream `main` does not yet contain the viewer, grid or visibility base
that VIEW-1/VIEW-4/GRID-1 depend on. Opening those as "first wave" branches
would have pulled unrelated features into the same PR. The first wave was
therefore reduced to self-contained units:

- [x] [#16 `feat(loads): point loads inside frame elements`](https://github.com/ogunc/opensees-studio/pull/16)
  - 22 files; includes the two force-based frame load fixes.
  - All required checks green; merged into `upstream/main`.
- [x] [#17 `fix(runner): a 2D ndf-3 truss run does not inherit the previous 3D truss state`](https://github.com/ogunc/opensees-studio/pull/17)
  - 4 files; process-state regression with a fake solver, no OpenSees needed.
  - All required checks green; merged into `upstream/main`.

### Second wave status (2026-10-26)

- [x] [#18 `feat(transient): modal damping over the first N modes`](https://github.com/ogunc/opensees-studio/pull/18)
  - 9 files, +232/−3; all required checks green; merged into `upstream/main`.
- [#19 `feat(canvas): select with a left-drag box`](https://github.com/ogunc/opensees-studio/pull/19)
  - 4 files, +153/−5; all required checks green.
  - This is the selection base needed by move/replicate/mirror; leave the
    transforms for a follow-up PR after this base is accepted.

The original second-wave candidates still need a prerequisite that is not yet on
`upstream/main`:

- **Multi-edit Properties** uses `FrameMember`, `FrameEndOffsets` and
  `CARDINAL_POINT_NAMES` from the later frame-options work.
- **Move/replicate/mirror** should follow #19 rather than duplicate its
  `core/selection.py` base.
- **Groups** uses storeys, diaphragms, mass source, area loads and load
  combinations.
- **Support springs** uses the frame-member plan and IFC export.

Those units should be sent only after their base feature, or together with it
in a deliberately larger PR. They are not independent first/second-wave
patches.



## Do not upstream

- `chore(release)` commits, version bumps, tags and generated bundles.
- The fork's release history in `CHANGELOG.md` (keep release notes in the fork).
- Packaging/branding changes unless the maintainer asks for them.
- Local SAP2000 `.s2k`/`.$2k` files, run snapshots, generated benchmark output
  and personal `CLAUDE.md` instructions.
- A copy of the fork's private data or generated catalog unless its
  provenance/licence is clear.

## Per-PR checklist

```bash
git fetch upstream
git switch -c <type>/<short-name> upstream/main
# port only the commits/files for this unit
git cherry-pick -x <commits>
# or adapt the files from the fork by hand
ruff check src tests
ruff format --check src tests
python tools/typecheck.py
lint-imports
pytest tests/unit tests/integration tests/tools
pytest tests/gui
```

Before opening the PR:

- `git diff upstream/main...HEAD --stat` must show only the unit.
- No release/version/CHANGELOG-release commits.
- Tests are added or updated in the same PR.
- The PR body names dependencies and any behavior/schema change.
- If `AXIS-1` is not accepted, convert the 2D tests/examples of that unit to
  the original's X-Y convention instead of carrying the fork's X-Z convention
  into upstream.

## Known integration decisions to discuss with the maintainer

1. **2D axis convention.** The fork uses X-Z with Z up; the original uses
   X-Y. The merged model check now understands both, but upstreaming the
   convention itself changes every 2D model, example and test. Make this a
   separate, explicitly agreed change.
2. **Check Model vs. numerical stability.** Upstream already has a kinematic
   `Check Model` (F6). The fork's `Check Model Stability` is an OpenSees
   tangent-stiffness check with sparse eigenvalues. They overlap but answer
   different questions; coordinate the UI wording and whether both remain.
3. **Schema and persistence.** The fork carries schema v3 and additive fields.
   Each field family needs its own compatibility tests and `omit_when_default`
   behavior.
4. **Optional engines.** PyNite and engine dispatch add a second analysis path;
   keep them behind an optional extra and a separate PR.
5. **S2K.** Treat the importer as a project, not one PR: baseline, sections,
   cases, wave 1, structural options, docs. Each stage needs fixtures built
   inline; never commit a real SAP2000 export.

## Next action

Push this reconciliation branch to the fork, keep it as the new fork baseline,
then create the first unit branch from `upstream/main`:

```bash
git switch -c ci/harden-jobs upstream/main
git cherry-pick <CI-1 commits>
```

Do not open the reconciliation branch as a PR to `ogunc/opensees-studio`.
