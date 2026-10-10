# `aisc_v16.csv` — AISC v16 shape table

Section properties of 1660 standard shapes: W, HP, M, S, C, MC, WT, MT, ST, L,
PIPE, HSS (rectangular and square) and HSS_R (round).

**Units are US customary**, as published: inches, in², in⁴, in⁶ and lb/ft. The
application converts to the project's unit system when a shape is inserted
(length² and length⁴ factors), and shows the converted values in the dialog.

## Where the numbers come from

- **AISC Shapes Database v16.0** / Steel Construction Manual, 16th edition —
  the properties themselves.
- **[steelpy](https://pypi.org/project/steelpy/)** 1.1.1 (Apache-2.0), whose
  shape files state they are consistent with the 16th edition — the machine
  readable form this table is generated from. Its licence text is kept beside
  this file as `LICENSE-steelpy.txt`, as Apache-2.0 requires.

The columns are a subset: geometry (`d`, `bf`, `tw`, `tf`, `od`, `tnom`) and
the properties a frame section needs (`area`, `ix`, `iy`, `j`, `cw`) plus the
ones the picker shows (`weight`, `zx`, `sx`, `rx`, `zy`, `sy`, `ry`). Double
angles are left out: a built-up section has its own axis conventions and the
application has no model for it.

Nobody transcribed these by hand. Regenerate with:

```bash
pip download --no-deps --dest /tmp/steelpy steelpy
python -c "import zipfile; zipfile.ZipFile('/tmp/steelpy/steelpy-1.1.1-py3-none-any.whl').extractall('/tmp/steelpy')"
python tools/build_aisc_data.py --source /tmp/steelpy/steelpy/"shape files"
```

`tests/unit/test_aisc.py` checks the table's internal consistency on every row
(radii of gyration against areas and inertias, section moduli against depth,
plastic against elastic) and recomputes one whole family from first
principles: round HSS, where AISC's design-wall-thickness rule
(`t_des = 0.93 t_nom`) reproduces the published A, I and J to within the
rounding of a three-significant-figure table. A wrong or missing row fails the
suite.

## Cross-check against an independent edition

The values were also compared with `aiscpy` (GPL-3.0), an unrelated package
whose database is the AISC **13th** edition — an older edition, so a handful of
properties legitimately differ:

| Family | Shapes in common | Ix within 1% | A within 0.1 in² |
| --- | --- | --- | --- |
| W, M, S, HP | 303 | **303 / 303** | 248 / 303 |
| C, MC | 28 | 28 / 28 | 27 / 28 |

The area differences are one rounding step at the published 0.1 in²
granularity, not disagreements. No shape in common differed on Ix.

That check is recorded rather than automated: it needs an external database
that the repository does not ship, and pinning a second dataset to make a test
green would prove less than the consistency and closed-form checks do.


## A note on redistribution

The properties are facts published by AISC, and this file is generated from an
Apache-2.0 package that publishes them. If you redistribute this application
commercially, satisfy yourself about AISC's own terms for the Shapes Database;
that review has not been done here.


# `typical_materials.csv` — typical construction materials

23 named materials an engineer reaches for on most jobs, each tied to the
clause its numbers come from, and each one mapped to the OpenSees material the
application will insert:

- **Concrete** (7) — `Concrete01`, unconfined Kent-Scott-Park: f'c from 2500 psi
  (17.2 MPa, ACI's minimum structural strength is 17 MPa) to 6000 psi, one of
  them lightweight.
- **Reinforcing steel** (6) — `Steel02`: ACI's Grade 280 / 420 / 550 and the
  ASTM A706 Grades 420 / 550 / 690.
- **Structural steel** (5) — `Steel02` for A992, A36, A572 Gr. 50 and A500
  Gr. B, plus one plain `Elastic` for a model that will stay elastic.
- **Masonry** (5) — `ElasticIsotropic`: clay brick at f'm = 1500 and 2000 psi,
  concrete block (normal weight, grouted, lightweight).

**Units are SI**: strengths and moduli in MPa, mass densities in kg/m³,
strains dimensionless. The application converts to the project's unit system
when a material is inserted, and the picker shows the published value beside
the converted one.

## Where the numbers come from

| Quantity | Source |
| --- | --- |
| `Ec` of concrete | **ACI 318-25** Eq. (19.2.2.1b), `Ec = 4700√f'c` (MPa), normalweight; Eq. (19.2.2.1a), `Ec = wc^1.5·0.043√f'c`, for the lightweight entry |
| Ultimate compression strain 0.003 | **ACI 318-25** §22.2.2.1 |
| Minimum structural f'c = 17 MPa | **ACI 318-25** §19.2.1.1 |
| `Es` = 29 000 ksi | **ACI 318-25** §20.2.2.2 (200 000 MPa) |
| Reinforcing grades 280 / 420 / 550 | **ACI 318-25** §20.2.2.4; A706 Grades 420 / 550 / 690, §18.2.6.1 |
| Historic bar grades | **ASCE 41-23** Table 4-3 |
| `Fy`/`Fu` of structural steel, `E` | **AISC 360-22** Chapter A (A992 50/65 ksi, A36 36/58, A572 Gr. 50 50/65, A500 Gr. B 46/58) |
| Masonry modulus `Em` | **TMS 402/602** — 700 f'm for clay masonry, 900 f'm for concrete masonry; **ASCE 41-23** §11.2.3.4 names TMS 402 as the source of the masonry modulus |
| Densities | **ASCE 7-16** Table C3.1-2: reinforced concrete 150 lb/ft³, hard clay brick 130, normal-weight concrete units 135, lightweight units 105, masonry grout 140, steel 492 |

Exact conversions are used, not rounded tables: 1 lb/ft³ = 16.01846337396014
kg/m³ (from 1 lb = 0.45359237 kg and 1 ft³ = 0.028316846592 m³) and
1 psi = 0.006894757293168361 MPa (from 1 lbf = 4.4482216152605 N and
1 in² = 0.00064516 m²).

The strains and the shape parameters are conventions rather than published
constants, and the file says so in each row: `epsc0 = 0.002`, crushing at
`0.2 f'c`, `b = 0.01` for reinforcement and `0.02` for structural steel (a
modelling choice), and OpenSees' own defaults `R0 = 18`, `cR1 = 0.925`,
`cR2 = 0.15`. Nothing in the table is transcribed by hand: regenerate with

```bash
python tools/build_typical_materials.py          # write the csv
python tools/build_typical_materials.py --check  # fail if the file drifted
```

`tests/unit/test_material_catalog.py` re-runs the generator, checks every
derived number against its code equation (ACI's two `Ec` expressions agree at
2320 kg/m³, the masonry modulus factor, the psi/ksi/kg-m³ conversions), and
runs one library material through the real solver.

Masonry is elastic in this library: an existing wall's nonlinear backbone is a
per-building decision (ASCE 41 Chapter 11), not a table lookup, so the picker
says so rather than inventing a crushing strain.
