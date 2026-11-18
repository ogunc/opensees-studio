# Results changes

Every change to the numbers OpenSees Studio produces for its own examples, with
the value before and after. `tools/results_snapshot.py` pins a fingerprint of
each example case in `tests/data/results_snapshots.json` (largest displacement
per DOF, reaction sums, largest element force, norms, periods, step counts) and
CI fails when one moves by more than 1e-5 relative. A fix that changes results
on purpose is pinned with

```bash
python tools/results_snapshot.py --write --reason "what changed and why"
```

which appends the table below and is announced under **Results changed** in
`CHANGELOG.md`. An entry here is what to re-check in your own models.

Changes that predate the snapshots (before 0.0.57) are described in the
CHANGELOG only.

## 2026-11-13: SRSS response spectra: repeated modes aligned with the excitation (basis- and platform-independent)

| Example | Case | Quantity | Before | After |
|---|---|---|---|---|
| space_frame_3d | 4 | disp_max | [0.0138292, 0.0023943, 7.65388e-05] | [0.0140349, 1.4791e-15, 6.88994e-05] |
| space_frame_3d | 4 | force_max | 97117.3 | 98558.6 |
| space_frame_3d | 4 | reaction_max | [36784.5, 6345.59, 41512.3, 16794, 97117.3, 1.87229e-09] | [37327.8, 3.51477e-09, 37368.3, 9.0278e-09, 98558.6, 2.14695e-09] |

## 2026-11-13: rc_frame_earthquake: Rayleigh damping on the committed stiffness (rayleigh_beta_k_comm), as the Tcl reference, instead of the current tangent; the run now covers all 400 steps instead of stalling at step 98

| Example | Case | Quantity | Before | After |
|---|---|---|---|---|
| rc_frame_earthquake | 1 | final_disp_max | [1.27482, 0.0471874, 0.0070795] | [0.121485, 0.0217348, 0.000784245] |
| rc_frame_earthquake | 1 | final_disp_norm | 1.80358 | 0.174384 |
| rc_frame_earthquake | 1 | n_steps | 98 | 400 |
| rc_frame_earthquake | 1 | peak_disp_max | [1.27482, 0.0471874, 0.0070795] | [1.64423, 0.0939533, 0.00802416] |
| rc_frame_earthquake | 1 | peak_disp_norm | 7.17385 | 18.8187 |
| rc_frame_earthquake | 1 | peak_force_max | 5165.87 | 5188.52 |
| rc_frame_earthquake | 1 | peak_force_norm | 52117.8 | 116827 |
| rc_frame_earthquake | 1 | time_final | 0.98 | 4 |

## 2026-11-13: mode-1 Rayleigh damping (rayleigh_mode1_damping) applied to the committed stiffness, as the Tcl idiom rayleigh 0 0 0 2*zeta/omega1, instead of the current tangent; ex4_portal2d_inelastic_fiber_section now covers all 1000 steps instead of stopping at step 37

| Example | Case | Quantity | Before | After |
|---|---|---|---|---|
| ex2c_canti2d_inelastic_fiber_section | 3 | final_disp_max | [0.199038, 0.0892168, 0.000693452] | [0.199125, 0.0892164, 0.000693755] |
| ex2c_canti2d_inelastic_fiber_section | 3 | final_disp_norm | 0.21812 | 0.218199 |
| ex2c_canti2d_inelastic_fiber_section | 3 | peak_disp_max | [0.594721, 0.0892168, 0.00206077] | [0.594637, 0.0892164, 0.00206048] |
| ex2c_canti2d_inelastic_fiber_section | 3 | peak_disp_norm | 5.65802 | 5.65757 |
| ex2c_canti2d_inelastic_fiber_section | 3 | peak_force_max | 30628.9 | 30624.7 |
| ex2c_canti2d_inelastic_fiber_section | 3 | peak_force_norm | 271803 | 271778 |
| ex3_canti2d_inelastic_fiber_section | 3 | peak_disp_max | [0.402587, 0.0733618, 0.00139713] | [0.40257, 0.0733612, 0.00139707] |
| ex3_canti2d_inelastic_fiber_section | 3 | peak_disp_norm | 4.45677 | 4.45662 |
| ex3_canti2d_inelastic_fiber_section | 3 | peak_force_max | 28827.7 | 28826.3 |
| ex3_canti2d_inelastic_fiber_section | 3 | peak_force_norm | 289381 | 289369 |
| ex4_portal2d_inelastic_fiber_section | 3 | final_disp_max | [1.49039, 0.00905251, 0.00158789] | [0.378417, 0.0383472, 0.0011438] |
| ex4_portal2d_inelastic_fiber_section | 3 | final_disp_norm | 2.10666 | 0.536297 |
| ex4_portal2d_inelastic_fiber_section | 3 | n_steps | 37 | 1000 |
| ex4_portal2d_inelastic_fiber_section | 3 | peak_disp_max | [1.52205, 0.0471922, 0.0016006] | [2.29176, 0.0799158, 0.00174551] |
| ex4_portal2d_inelastic_fiber_section | 3 | peak_disp_norm | 8.0974 | 29.6574 |
| ex4_portal2d_inelastic_fiber_section | 3 | peak_force_max | 112228 | 112607 |
| ex4_portal2d_inelastic_fiber_section | 3 | peak_force_norm | 1.00556e+06 | 3.05097e+06 |
| ex4_portal2d_inelastic_fiber_section | 3 | time_final | 0.37 | 10 |
| ex4_portal2d_inelastic_section | 3 | final_disp_max | [0.60892, 0.0852234, 0.00243956] | [0.607367, 0.0852164, 0.00243866] |
| ex4_portal2d_inelastic_section | 3 | final_disp_norm | 0.868311 | 0.866133 |
| ex4_portal2d_inelastic_section | 3 | peak_disp_max | [2.36725, 0.102047, 0.00304298] | [2.36568, 0.102039, 0.00304208] |
| ex4_portal2d_inelastic_section | 3 | peak_disp_norm | 31.767 | 31.735 |
| ex4_portal2d_inelastic_section | 3 | peak_force_max | 132561 | 135138 |
| ex4_portal2d_inelastic_section | 3 | peak_force_norm | 3.03968e+06 | 3.03962e+06 |
