# Official structural examples 01 to 07

Each numbered Python builder uses the same commands as the desktop dialogs.
Run a builder with `python -m examples.official.01_elastic_truss`, replacing
the module name as needed. Open its generated `.osmodel` and use Analyze > Run.
No builder constructs model JSON or runs OpenSees directly.

References: [published structural examples](https://openseespydoc.readthedocs.io/en/latest/src/structure.html).
The files in `tests/reference/official_structural` contain source URLs, SHA256
hashes, OpenSeesPy version, final scalars and full-precision curves. Source
script text is not stored in this repository. Inputs retain the published
numeric values without unit conversion; model display units are inch and kip.

Validation builds, saves, solves through the production CLI, compares every
reference scalar and curve point, reopens and solves again, and checks identical
CSV exports and result arrays. Relative tolerances are 1e-8 for linear elastic
results and 1e-5 for nonlinear results and curves, with absolute floor 1e-12.
Reported relative differences exclude reference magnitudes at or below 1e-12;
those quantities must still pass the absolute-floor assertion.

| Example | Compared quantities | Substitutions and mappings |
|---|---|---|
| 01 Elastic truss | 14 displacement/reaction scalars | None; source tags retained |
| 02 Nonlinear truss | 14 scalars; 1001 load/displacement points | None; Hardening and original static steps |
| 03 Portal frame | 94 scalars including seven periods and global element forces | Auto dense eigen solver instead of ARPACK; equivalent static solver defaults made explicit; source tags retained |
| 04 Moment curvature | 12 scalars; 102 curve points | SparseGeneral without its ignored `-piv` flag; explicit Constant preload case; curve includes the undeformed point |
| 05 RC gravity | 18 scalars | None; PDelta columns, Lobatto 5 |
| 06 RC pushover | 18 scalars; 161 gravity/pushover points | None; gravity preload and ModifiedNewton `-initial`; 151 increments reproduce the published loop's final 15.1 displacement |
| 07 Steel frame | 81 scalars; 181 pushover, 11 gravity and 180 fiber points | WFSection2d replaced by the W-shape editor template; node/element maps in the builder; Lobatto 4, PDelta columns |

Example 07's source fiber index 1 maps to template fiber index 13 (zero based)
in element 102, section 4. The source numbers upper-flange fibers from outside
inward; rectangular patches enumerate ascending y. Both refer to
`y = 8.3/2 - 1.5*0.685/15 = 4.0815`, z = 0. This mapping follows
[WideFlangeSectionIntegration](https://github.com/OpenSees/OpenSees/blob/master/SRC/material/section/integration/WideFlangeSectionIntegration.cpp).
The published Steel02 isotropic parameters are retained, not substituted.

Example 08 (FRP) is excluded because its material is absent from OpenSeesPy 3.8.0.
