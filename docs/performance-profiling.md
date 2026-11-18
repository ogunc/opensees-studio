# Performance profiling on large models

OpenSees Studio ships with an **opt-in** performance monitor. A normal run pays
one boolean check at each instrumented boundary; nothing is recorded, formatted
or written unless you ask for it.

The goal is to answer, with numbers, where a large model spends its time. The
same report shows the SAP2000 importer, project I/O, the analysis child, the
scene builder and the undoable commands, so a slow action can be attributed to a
layer instead of guessed.

## Enable it

Any of these turns collection on:

```bash
python -m opensees_studio --profile
python -m opensees_studio --perf-json report.json
OPENSEES_STUDIO_PERF=1 python -m opensees_studio
```

Frozen builds accept the same flags:

```bash
OpenSeesStudio.exe --profile
```

Inside a running application, open **Help → Performance monitor** and press
**Enable profiling**. This is useful when the slow operation is already
reproducible and you do not want to relaunch.

`--perf-json PATH` writes a snapshot on exit. The snapshot is also available from
the dialog's **Save JSON** and **Copy JSON** buttons, which is the format to
attach to an issue.

## What the table means

Each row is an instrumented boundary:

| Prefix | Stage |
| --- | --- |
| `s2k.*` | SAP2000 text parsing and translation (joints, materials, frames, patterns, cases, nonprismatic materialisation, validation) |
| `persistence.*` | Reading, migrating, validating, serialising and writing a `.osmodel` |
| `analysis.*` | Snapshot, model build, checks, and each case type (static, modal, spectrum, pushover, transient, influence line) |
| `analysis.run_wall` | Parent-observed duration of a GUI analysis, including the child process |
| `render.*` | Scene construction per category (grid, nodes, frames, surfaces, supports, loads, reactions, labels, extrusions) |
| `command.*` | Undoable commands, named after their class |
| `ui.*` | High-level window actions such as importing an S2K file |
| `bench.*` | Stages measured by `tools/perf_bench.py` |

Columns:

- **Last ms** – the most recent sample.
- **Total ms** – sum of every sample since the last reset.
- **N** – number of samples.
- **p95 ms** – 95th percentile of the last 512 samples.
- **Max ms** – worst sample.

Nested spans (for example `render.build` containing `render.loads`) are both
listed. The outer row is the total for the operation; the inner rows show where
that total went.

The footer shows counters, gauges (model sizes and actor counts) and the number
and worst duration of **UI stalls**: gaps in a 200 ms heartbeat that indicate an
operation blocked the Qt event loop.

## Profile the next action

**Profile next action** arms a one-shot `cProfile` around the next top-level
instrumented operation. Do the slow thing (run an analysis, import a file, apply
a large command, rebuild the scene) and the dialog shows the 30 functions with
the largest cumulative time.

This is the quickest way to distinguish “the model is big, so the renderer is
busy” from “a Python loop is doing quadratic work”.

## Repeatable benchmark

`tools/render_bench.py` measures the renderer alone and is the CI budget ratchet.
`tools/perf_bench.py` measures the surrounding stages on a synthetic grid with
supports and loads:

```bash
python tools/perf_bench.py --size small
python tools/perf_bench.py --size large --profile
python tools/perf_bench.py --size xlarge --profile --json > report.json
python tools/perf_bench.py --size large --solver --cprofile
```

Sizes:

| Name | Grid | Nodes |
| --- | --- | --- |
| `tiny` | 4 × 4 × 2 | 32 |
| `small` | 6 × 6 × 3 | 108 |
| `medium` | 10 × 10 × 5 | 500 |
| `large` | 14 × 14 × 8 | 1 568 |
| `xlarge` | 20 × 20 × 10 | 4 000 |

`--solver` adds a static case and measures the in-process `OpenSeesRunner`; omit
it on machines without OpenSeesPy. `--json` is machine-readable; `--cprofile`
prints a function profile to stderr so the JSON stays clean.

Run the same command before and after a change. Compare `wall_ms` and the
`render`, `save` and `load` stages; do not compare absolute numbers across
machines.

## Interpreting a report

A practical order:

1. Look at `render.build` and its children. `render.loads` and `render.nodes` are
   usually the largest for dense models; `render.supports` grows with the number
   of restrained joints.
2. Look at `s2k.*` if import is slow. A large `s2k.frames` is expected; a large
   `s2k.nonprismatic` points at subdivision work.
3. Look at `persistence.serialize` / `persistence.validate` for save/open cost;
   Pydantic validation is often the dominant part of opening a large file.
4. Look at `analysis.run_wall` versus the child's own result. If the parent wall
   time is much larger than the solver time reported by the child, the overhead
   is snapshot, startup, JSON line protocol or result loading.
5. Look at the UI stalls and `command.*` rows for actions that block the event
   loop. The fix is usually to batch, debounce or move work to a worker.

## Limitations

- Timings are wall-clock and include the cost of the instrumentation (small, but
  not zero). They are meant for relative comparisons, not certification.
- The GUI runs analyses in a child process. The parent measures the whole child
  (`analysis.run_wall`) and the snapshot/result-loading stages; the child's own
  fine-grained spans are not merged into the parent report yet.
- Python memory tracking is explicit: call `perf.start_memory_tracing()` (not
  enabled by default because `tracemalloc` adds measurable overhead). The report
  always includes process RSS when `psutil` is available.
- `--profile` must come before Qt starts; inside the application use the dialog.
- The report is diagnostic data only. It never includes model geometry or SAP2000
  files.
