"""Annex of the help: a glossary of every command of the OpenSeesPy manual.

One page per family of commands (the chapters of the OpenSeesPy documentation).
Each entry names the command, says in a line what it does, and where it lives in
OpenSees Studio:

* a menu path — the application has a form for it;
* ``AUTO`` — the runner emits it for you from the model (you never type it);
* ``CUSTOM`` — no form yet: write it in Define → Custom OpenSees Commands;
* ``OUT`` — outside the scope of a structural desktop tool (parallel computing,
  fluid-structure interaction …); a custom block can still issue it when the
  installed OpenSeesPy supports it.

The descriptions are the application's own short summaries; the OpenSeesPy manual
(openseespydoc.readthedocs.io) is the reference for every argument. ``core.help``
merges :data:`GLOSSARY_TOPICS` into its pages. No Qt, no OpenSees.
"""

from __future__ import annotations

AUTO = "automatic (the runner emits it from the model)"
CUSTOM = "Define → Custom OpenSees Commands"
OUT = "outside the scope of the application (a custom block may issue it)"
MAT = "Define → Material Library"
SEC = "Define → Section Library"
CASE = "Analyze → Cases"
LINK = "Assign → Joint → Link"
BEARING = "Assign → Joint → Bearing"
FRICTION = "Define → Friction Models"
INTEG = "Assign → Frame → Beam Integration"

#: page id → (title, summary, intro, entries (command, what it does, where))
_PAGES: dict[str, tuple[str, str, str, tuple[tuple[str, str, str], ...]]] = {
    "annex.model": (
        "Annex A — model, nodes, constraints, mass",
        "model, node, fix, mp constraints, mass, region, rayleigh, block, geomTransf, beamIntegration, frictionModel.",
        "The commands that define the domain: the space, the joints, how they are held and tied, their mass, the member transformations and integration rules.",
        (
            (
                "model",
                "Opens the model space: ndm dimensions and ndf DOF per node.",
                "File → New (2D frame, 2D truss, 3D frame); " + AUTO,
            ),
            (
                "node",
                "A joint at its coordinates, optionally with mass.",
                "Draw → Node, Define → Add Node, Edit → Interactive Table Editing",
            ),
            ("fix", "Restrains DOFs of one node.", "Assign → Joint → Restraints"),
            (
                "fixX / fixY / fixZ",
                "Restrains DOFs of every node at a given coordinate.",
                "Select the joints at that coordinate (Select menu, a window), then Assign → Joint → Restraints",
            ),
            (
                "equalDOF",
                "Ties DOFs of a constrained node to a retained one.",
                "Assign → Joint → EqualDOF",
            ),
            ("equalDOF_Mixed", "equalDOF with different DOFs on each side.", CUSTOM),
            (
                "rigidDiaphragm",
                "Makes the nodes of a floor move as a rigid plate.",
                "Assign → Joint → Diaphragm",
            ),
            ("rigidLink", "A rigid bar or beam between two nodes.", "Assign → Joint → Rigid Link"),
            ("pressureConstraint", "Pressure DOF of fluid (PFEM) models.", OUT),
            ("mass", "Lumped nodal mass per DOF.", "Assign → Joint → Masses, Define → Mass Source"),
            (
                "region",
                "A named set of nodes/elements, e.g. for Rayleigh factors per region.",
                "Define → Groups (selection); per-region damping: " + CUSTOM,
            ),
            ("rayleigh", "Rayleigh damping factors αM, βK, βKinit, βKcomm.", CASE + " → Transient"),
            (
                "block2D / block3D",
                "Generates a mesh of quads or bricks over a block.",
                "Edit → Mesh and Define → Create Shell from 4 Nodes; bricks: " + CUSTOM,
            ),
            (
                "geomTransf Linear",
                "Small-displacement transformation of a frame member.",
                "Assign → Frame → Geometric Transformation",
            ),
            (
                "geomTransf PDelta",
                "Linear transformation plus P-Delta effects.",
                "Assign → Frame → Geometric Transformation",
            ),
            (
                "geomTransf Corotational",
                "Large-displacement (corotational) transformation.",
                "Assign → Frame → Geometric Transformation",
            ),
            (
                "beamIntegration Lobatto / Legendre / NewtonCotes / Radau / Trapezoidal",
                "Gauss-type rules along a force- or displacement-based member.",
                INTEG,
            ),
            (
                "beamIntegration CompositeSimpson",
                "Composite Simpson rule.",
                "not offered (its result differs from the tutorials); " + CUSTOM,
            ),
            (
                "beamIntegration UserDefined / FixedLocation / LowOrder / MidDistance",
                "Rules with chosen locations or weights.",
                CUSTOM,
            ),
            (
                "beamIntegration UserHinge / HingeMidpoint / HingeRadau / HingeRadauTwo / HingeEndpoint",
                "Plastic-hinge integration: hinge sections at the ends, elastic interior.",
                "Assign → Frame → Plastic Hinge (beamWithHinges); other hinge rules: " + CUSTOM,
            ),
            (
                "frictionModel Coulomb / VelDependent / VelNormalFrcDep",
                "Friction laws of sliding bearings.",
                FRICTION,
            ),
            (
                "frictionModel VelPressureDep / VelDepMultiLinear",
                "Pressure- or multilinear velocity-dependent friction.",
                CUSTOM,
            ),
        ),
    ),
    "annex.elements": (
        "Annex B — elements",
        "Every element family of the manual and where each is created.",
        "Elements connect the nodes. Frame members are drawn or generated; joints-to-joint devices are assigned to two selected joints; faces are created from four joints or by meshing.",
        (
            (
                "zeroLength",
                "Springs (one uniaxial material per DOF) between two coincident nodes.",
                "Assign → Frame → Releases/Partial Fixity, Assign → Joint → Springs (both "
                + AUTO
                + "); a free-standing one: "
                + CUSTOM,
            ),
            ("zeroLengthND", "Zero-length element with an nD material.", CUSTOM),
            (
                "zeroLengthSection",
                "A section (moment-curvature) between two coincident nodes.",
                "Assign → Joint → Zero-Length Section",
            ),
            (
                "CoupledZeroLength / zeroLengthContact / zeroLengthContactNTS2D / zeroLengthInterface2D / zeroLengthImpact3D",
                "Coupled, contact and impact zero-length elements.",
                CUSTOM,
            ),
            (
                "Truss / corotTruss",
                "Axial bar, small or large displacements.",
                "Draw → Truss, Define → Create Truss",
            ),
            (
                "elasticBeamColumn",
                "Linear-elastic frame member.",
                "Draw → Frame, Define → Create Portal Frame",
            ),
            (
                "ModElasticBeam2d",
                "Elastic beam with stiffness modifiers (2D).",
                "Assign → Frame → Property Modifiers (on elasticBeamColumn)",
            ),
            (
                "ElasticTimoshenkoBeam",
                "Elastic member with shear deformation.",
                "an Elastic section with shear areas As2/As3 (" + SEC + ")",
            ),
            (
                "beamWithHinges",
                "Elastic interior with plastic-hinge sections at the ends.",
                "Assign → Frame → Plastic Hinge",
            ),
            (
                "dispBeamColumn / forceBeamColumn / nonlinearBeamColumn",
                "Distributed-plasticity members on fibre sections.",
                "Edit → Interactive Table Editing / Properties panel (element type), " + INTEG,
            ),
            (
                "dispBeamColumnInt",
                "Flexure-shear interaction displacement-based member.",
                "Properties panel (element type)",
            ),
            (
                "MVLEM / SFI_MVLEM / MVLEM_3D / SFI_MVLEM_3D",
                "Multiple-vertical-line models of RC walls.",
                CUSTOM + " (or a LayeredShell wall: " + SEC + ")",
            ),
            ("Pipe / CurvedPipe", "Elastic straight and curved pipe elements.", CUSTOM),
            (
                "beamColumnJoint / ElasticTubularJoint / Joint2D",
                "Panel-zone joint elements.",
                CUSTOM + " (a twoNodeLink spring: " + LINK + ")",
            ),
            ("twoNodeLink", "One uniaxial material per local direction between two nodes.", LINK),
            (
                "elastomericBearingPlasticity / elastomericBearingBoucWen",
                "Elastomeric isolators (bilinear or Bouc-Wen shear).",
                BEARING,
            ),
            (
                "flatSliderBearing / singleFPBearing",
                "Flat slider and single friction pendulum isolators.",
                BEARING,
            ),
            ("TripleFrictionPendulum", "Triple friction pendulum isolator (3D).", LINK),
            (
                "TFP / FPBearingPTV / MultipleShearSpring / KikuchiBearing / YamamotoBiaxialHDR / RJWatsonEqsBearing",
                "Other isolator formulations.",
                CUSTOM,
            ),
            (
                "ElastomericX / LeadRubberX / HDR",
                "Physical elastomeric isolator models.",
                "not offered: their vertical response could not be validated in OpenSees 3.8; "
                + CUSTOM,
            ),
            (
                "quad / bbarQuad / enhancedQuad",
                "Four-node plane elements.",
                "examples and scripts; " + CUSTOM,
            ),
            (
                "ShellMITC4",
                "Four-node shell (membrane + plate).",
                "Define → Create Shell from 4 Nodes, Edit → Mesh",
            ),
            (
                "ShellDKGQ / ShellDKGT / ShellNLDKGQ / ShellNLDKGT / ShellNL",
                "Other shell formulations, linear and geometrically nonlinear.",
                CUSTOM,
            ),
            ("SSPquad / SSPbrick", "Stabilised single-point plane and brick elements.", CUSTOM),
            ("tri31", "Three-node plane element.", CUSTOM),
            ("stdBrick / bbarBrick / 20NodeBrick / FourNodeTetrahedron", "Solid elements.", CUSTOM),
            (
                "quadUP / brickUP / bbarQuadUP / bbarBrickUP / 9_4_QuadUP / 20_8_BrickUP / SSPquadUP / SSPbrickUP",
                "Saturated-soil (u-p) elements.",
                OUT,
            ),
            (
                "SimpleContact2D / SimpleContact3D / BeamContact2D / BeamContact3D / BeamEndContact3D",
                "Contact elements.",
                CUSTOM,
            ),
            ("CatenaryCable", "Cable element with sag.", CUSTOM),
            (
                "PFEMElementBubble / PFEMElementCompressible",
                "Particle finite-element fluid elements.",
                OUT,
            ),
            (
                "SurfaceLoad / VS3D4 / AC3D8 / ASI3D8 / AV3D4 / MasonPan12",
                "Surface-load, absorbing, acoustic and masonry-panel elements.",
                CUSTOM,
            ),
        ),
    ),
    "annex.uniaxial": (
        "Annex C — uniaxial materials",
        "Every uniaxialMaterial of the manual and where it is defined.",
        "A uniaxial material is a stress-strain (or force-deformation) law. Trusses, springs, links and the fibres of a section use them. Those with a form are added from "
        + MAT
        + " and can be checked in Define → Material Tester.",
        (
            ("Elastic", "Linear elastic, optionally different in compression.", MAT),
            ("ElasticPP", "Elastic-perfectly plastic.", MAT),
            ("ElasticPPGap", "Elastic-perfectly plastic with an initial gap.", MAT),
            ("ENT", "Elastic, no tension.", CUSTOM),
            ("Hardening", "Plasticity with isotropic and kinematic hardening.", MAT),
            ("Steel01", "Bilinear steel, kinematic hardening.", MAT),
            ("Steel02", "Giuffré-Menegotto-Pinto steel.", MAT),
            ("Steel4", "Steel with asymmetric, isotropic and ultimate options.", CUSTOM),
            ("ReinforcingSteel", "Chang-Mander reinforcing bar (base options).", MAT),
            (
                "Dodd_Restrepo / RambergOsgoodSteel / SteelMPF / Steel01Thermal",
                "Other steel laws.",
                CUSTOM,
            ),
            ("Concrete01", "Kent-Scott-Park, no tension.", MAT),
            ("Concrete02", "Kent-Scott-Park with linear tension softening.", MAT),
            ("Concrete04", "Popovics concrete with optional tension.", MAT),
            ("Concrete06", "Thorenfeldt-base concrete with tension stiffening.", MAT),
            ("Concrete07", "Chang-Mander concrete.", MAT),
            (
                "Concrete02IS / Concrete01WithSITC / ConfinedConcrete01 / ConcreteD / FRPConfinedConcrete / FRPConfinedConcrete02 / ConcreteCM",
                "Other concrete laws.",
                CUSTOM,
            ),
            (
                "TDConcrete / TDConcreteEXP / TDConcreteMC10 / TDConcreteMC10NL",
                "Time-dependent (creep and shrinkage) concrete.",
                CUSTOM,
            ),
            ("Hysteretic", "Trilinear hysteretic law with pinching and damage.", MAT),
            ("HystereticSM", "Multi-point hysteretic law, asymmetric envelopes.", MAT),
            ("Parallel", "Materials side by side: stresses added.", MAT),
            ("Series", "Materials in series: strains added.", MAT),
            ("PySimple1 / TzSimple1 / QzSimple1", "p-y, t-z and q-z springs of piles.", MAT),
            ("PyLiq1 / TzLiq1 / QzLiq1", "Pile springs in liquefiable soil.", OUT),
            ("CastFuse", "Cast steel fuse.", CUSTOM),
            ("Damper (wrapper)", "Turns a material into a damper of the strain rate.", CUSTOM),
            ("ViscousDamper", "Maxwell spring-dashpot damper.", MAT),
            ("BilinearOilDamper", "Oil damper with a relief valve.", MAT),
            ("Bilin", "Modified Ibarra-Medina-Krawinkler, bilinear hysteresis.", MAT),
            ("ModIMKPeakOriented", "Modified IMK, peak-oriented hysteresis.", MAT),
            ("ModIMKPinching", "Modified IMK, pinched hysteresis.", MAT),
            ("SAWS", "Wood shear wall hysteresis.", CUSTOM),
            ("BarSlip / Bond_SP01", "Bar slip and strain penetration at anchorages.", CUSTOM),
            ("Fatigue", "Low-cycle fatigue wrapper (Coffin-Manson).", MAT),
            ("MultiplierUni", "Scales the stress of another material.", CUSTOM),
            ("Impact / HyperbolicGapMaterial", "Impact and hyperbolic gap laws.", CUSTOM),
            ("LimitState", "Hysteretic law with a limit curve (shear failure).", CUSTOM),
            ("MinMax", "Failure outside a strain range.", MAT),
            ("ElasticBilin", "Bilinear elastic.", MAT),
            ("ElasticMultiLinear", "Multilinear elastic through points.", MAT),
            ("MultiLinear", "Multilinear hysteretic through points.", MAT),
            (
                "InitStrainMaterial / InitStressMaterial",
                "Wraps a material with an initial strain or stress.",
                MAT,
            ),
            (
                "PenaltyUni / PathIndependent / SimpleFracture / TensionOnly",
                "Other wrappers.",
                CUSTOM,
            ),
            (
                "Pinching4",
                "Pinched response with stiffness and strength degradation.",
                MAT + " (symmetric envelope)",
            ),
            ("ECC01", "Engineered cementitious composite.", CUSTOM),
            ("SelfCentering", "Flag-shaped self-centering law.", CUSTOM),
            ("Viscous", "Nonlinear dashpot.", MAT),
            ("BoucWen", "Smooth Bouc-Wen hysteresis.", MAT),
            (
                "BWBN / KikuchiAikenHDR / KikuchiAikenLRB / AxialSp / AxialSpHD",
                "Bouc-Wen-Baber-Noori and isolator laws.",
                CUSTOM,
            ),
            (
                "PinchingLimitStateMaterial / CFSWSWP / CFSSSWP / Backbone / Masonry / Pipe",
                "Other specialised laws.",
                CUSTOM,
            ),
        ),
    ),
    "annex.nd": (
        "Annex D — nD materials",
        "Multi-dimensional materials for plane elements, solids and shell layers.",
        "nD materials describe stress-strain in 2D or 3D. In the application they serve the plate and layered-shell sections; soil and fluid models are for geotechnical tools.",
        (
            ("ElasticIsotropic", "Linear elastic, E and ν.", MAT),
            ("ElasticOrthotropic", "Linear elastic, orthotropic.", CUSTOM),
            ("J2Plasticity", "von Mises plasticity with hardening.", MAT),
            (
                "DruckerPrager / MultiaxialCyclicPlasticity / BoundingCamClay",
                "Pressure-dependent and clay plasticity.",
                OUT,
            ),
            ("PlaneStress / PlaneStrain", "Plane wrappers of a 3D material.", CUSTOM),
            ("PlateFiber", "Plate wrapper of a 3D material (a shell layer).", MAT),
            ("FSAM", "Fixed-strut-angle model of RC panels.", CUSTOM),
            (
                "ManzariDafalias / PM4Sand / PM4Silt / StressDensityModel / AcousticMedium / CycLiqCP / CycLiqCPSP",
                "Sand, silt and acoustic models.",
                OUT,
            ),
            ("PlateFromPlaneStress", "Plate wrapper of a plane-stress material.", MAT),
            ("PlateRebar", "A rebar layer at an angle.", MAT),
            (
                "PlasticDamageConcretePlaneStress",
                "Plane-stress concrete with plasticity and damage.",
                MAT,
            ),
            ("ContactMaterial2D / ContactMaterial3D", "Contact interface laws.", CUSTOM),
            (
                "InitialStateAnalysisWrapper / InitStressNDMaterial / InitStrainNDMaterial",
                "Initial-state wrappers.",
                OUT,
            ),
            (
                "PressureIndependMultiYield / PressureDependMultiYield (02, 03) / FluidSolidPorousMaterial",
                "UC San Diego soil models.",
                OUT,
            ),
        ),
    ),
    "annex.sections": (
        "Annex E — sections",
        "Every section of the manual: frame, fibre, plate and shell sections.",
        "A section gives a frame member or a shell its force-deformation response. Elastic and plate sections are typed in; fibre sections are drawn in the fibre section editor.",
        (
            ("Elastic", "E, A, I (and shear areas) of a linear frame section.", SEC),
            (
                "Fiber (with fiber, patch, layer)",
                "A section of fibres, each a uniaxial material.",
                SEC + " → fibre section editor",
            ),
            ("FiberThermal / NDFiber", "Thermal and nD-fibre sections.", CUSTOM),
            (
                "WFSection2d",
                "Wide-flange fibre section.",
                "fibre section editor → W-shape template",
            ),
            (
                "RCSection2d / RCCircularSection",
                "Reinforced concrete fibre sections.",
                "fibre section editor → RC rectangular / RC circular templates",
            ),
            ("Parallel", "Sections in parallel.", CUSTOM),
            ("Aggregator", "Adds uniaxial responses (shear, torsion) to a section.", SEC),
            ("Uniaxial", "A uniaxial material as a section response.", CUSTOM),
            ("ElasticMembranePlateSection", "Elastic shell section.", SEC),
            ("PlateFiber", "One plate material through the thickness.", SEC),
            ("LayeredShell", "Plate materials layer by layer (RC walls and slabs).", SEC),
            (
                "Bidirectional / Isolator2spring / Pipe",
                "Bidirectional, isolator and pipe sections.",
                CUSTOM,
            ),
        ),
    ),
    "annex.loads": (
        "Annex F — time series, patterns and loads",
        "timeSeries, pattern, load, eleLoad, sp, ground motions.",
        "A load pattern ties loads to a time series that scales them; ground-motion patterns apply accelerations or support motions.",
        (
            (
                "timeSeries Linear",
                "Factor proportional to time (a static ramp).",
                "Define → Add Linear TimeSeries",
            ),
            (
                "timeSeries Path",
                "Tabulated values (a record).",
                "Define → Add Path TimeSeries, Define → Ground Motions",
            ),
            (
                "timeSeries Constant / Trig / Triangle / Rectangular / Pulse",
                "Formula series.",
                "Define → Add Function TimeSeries",
            ),
            (
                "pattern Plain",
                "Nodal and element loads scaled by a series.",
                "Define → Add Plain Load Pattern",
            ),
            (
                "load",
                "A nodal force or moment.",
                "Assign → Joint → Point Loads, Edit → Interactive Table Editing",
            ),
            (
                "eleLoad -beamUniform / -beamPoint",
                "Span loads on frame members.",
                "Assign → Frame → Distributed / Trapezoidal / Point Load, Assign → Area → Floor Load",
            ),
            ("eleLoad -beamThermal", "Temperature gradients on members.", CUSTOM),
            (
                "sp",
                "An imposed displacement (settlement).",
                "Assign → Joint → Imposed Displacement",
            ),
            (
                "pattern UniformExcitation",
                "A base acceleration on the whole model.",
                "Define → Add Uniform Excitation",
            ),
            (
                "pattern MultipleSupport (groundMotion, imposedMotion)",
                "Different motions at different supports.",
                "Define → Add Multi-Support Excitation (one displacement series)",
            ),
            ("groundMotion Interpolated", "A ground motion interpolated between records.", CUSTOM),
        ),
    ),
    "annex.analysis": (
        "Annex G — analysis commands",
        "constraints, numberer, system, test, algorithm, integrator, analysis, eigen, analyze.",
        "These commands configure and run a solve. In the application an analysis case holds the choices and the runner emits them.",
        (
            (
                "constraints Plain / Lagrange / Penalty / Transformation",
                "How constraints and imposed values are enforced.",
                CASE,
            ),
            ("numberer Plain / RCM / AMD", "Order of the equations.", CASE),
            (
                "numberer ParallelPlain / ParallelRCM",
                "Numberers of the parallel interpreters.",
                OUT,
            ),
            (
                "system BandGeneral / BandSPD / ProfileSPD / SparseGeneral (SuperLU) / SparseSYM / UmfPack / FullGeneral",
                "Linear solver.",
                CASE,
            ),
            (
                "system Mumps / Diagonal / PythonSparse",
                "Parallel, lumped-mass explicit and Python-supplied solvers.",
                "not offered (platform or mass requirements); " + CUSTOM,
            ),
            (
                "test NormDispIncr / NormUnbalance / EnergyIncr / RelativeNormDispIncr / RelativeNormUnbalance / RelativeEnergyIncr / RelativeTotalNormDispIncr / NormDispAndUnbalance / NormDispOrUnbalance / FixedNumIter",
                "Convergence tests.",
                CASE,
            ),
            (
                "algorithm Linear / Newton / NewtonLineSearch / ModifiedNewton / KrylovNewton / SecantNewton / RaphsonNewton / PeriodicNewton / BFGS / Broyden",
                "Solution algorithms.",
                CASE,
            ),
            (
                "integrator LoadControl / DisplacementControl / ArcLength / MinUnbalDispNorm",
                "Static integrators.",
                CASE + " (DisplacementControl: Pushover cases)",
            ),
            ("integrator ParallelDisplacementControl", "Parallel static integrator.", OUT),
            (
                "integrator Newmark / HHT / GeneralizedAlpha / CentralDifference / TRBDF2",
                "Transient integrators.",
                CASE,
            ),
            (
                "integrator ExplicitDifference",
                "Explicit integrator.",
                "not offered (needs mass on every DOF); " + CUSTOM,
            ),
            ("analysis Static / Transient", "The analysis type.", AUTO),
            (
                "eigen",
                "Eigenvalues and mode shapes.",
                CASE + " → Modal (solver chosen automatically)",
            ),
            ("analyze", "Runs the steps.", "Analyze → Run"),
            (
                "modalProperties",
                "Modal participation reported by OpenSees.",
                "computed by the application (Display → Show Results Of, Modal tables)",
            ),
            (
                "responseSpectrumAnalysis",
                "Response spectrum solve inside OpenSees.",
                "the application's own Response Spectrum case (" + CASE + ")",
            ),
            ("modalDamping", "Damping ratio per mode.", CASE + " → Transient (modal damping)"),
        ),
    ),
    "annex.output": (
        "Annex H — output commands",
        "Node and element responses, recorders, section output, solver state.",
        "The runner reads what the Results panel and the plots show; the commands below are what it reads them with. Anything else is a custom block's.",
        (
            (
                "nodeDisp / nodeVel / nodeAccel / nodeReaction / reactions",
                "Nodal responses and support reactions.",
                AUTO + " → Results panel",
            ),
            (
                "eleForce / eleResponse (localForce, stresses)",
                "Element end forces and responses.",
                AUTO + " → force diagrams, shell contours",
            ),
            ("nodeEigenvector", "Mode shapes.", AUTO + " → Display → Animate Mode Shape"),
            (
                "recorder Node / Element",
                "Writes histories to files during a transient.",
                AUTO + " → Time-History and Hysteresis plots",
            ),
            (
                "recorder EnvelopeNode / EnvelopeElement / pvd / background / Collapse",
                "Envelope, ParaView and collapse recorders.",
                CUSTOM,
            ),
            (
                "sectionForce / sectionDeformation / sectionStiffness / sectionFlexibility / sectionLocation / sectionWeight",
                "Section response along a member.",
                CUSTOM,
            ),
            (
                "basicDeformation / basicForce / basicStiffness / eleDynamicalForce",
                "Element basic-system quantities.",
                CUSTOM,
            ),
            (
                "eleNodes / getEleTags / getNodeTags / nodeCoord / nodeBounds / nodeDOFs / nodeMass / nodePressure / nodeResponse / nodeUnbalance",
                "Queries of the domain.",
                CUSTOM,
            ),
            (
                "getLoadFactor / getTime / numFact / numIter / systemSize / testIter / testNorm",
                "Solver state.",
                CUSTOM,
            ),
            (
                "printA / printB",
                "Stiffness matrix and right-hand side.",
                "Analyze → Check Model Stability (printA)",
            ),
            (
                "printModel / printGID / record / version / logFile",
                "Print, export and log utilities.",
                CUSTOM,
            ),
        ),
    ),
    "annex.utility": (
        "Annex I — utility commands",
        "wipe, loadConst, remove, setTime, initial conditions and the rest.",
        "Utilities that change the domain between steps or manage the interpreter.",
        (
            ("wipe / wipeAnalysis", "Clear the model or the analysis.", AUTO),
            (
                "loadConst",
                "Holds the applied loads and resets time (preload).",
                CASE + " → Transient / Pushover (preload cases)",
            ),
            (
                "remove",
                "Removes a pattern, element, node, sp or recorder.",
                CASE + " → Transient (patterns to remove after preload); " + AUTO,
            ),
            ("modalDamping", "Damping per mode.", CASE + " → Transient"),
            ("reactions", "Computes reactions for output.", AUTO),
            ("setTime", "Sets the domain time.", CUSTOM),
            (
                "setNodeCoord / setNodeDisp / setNodeVel / setNodeAccel",
                "Changes coordinates or sets initial conditions.",
                CUSTOM,
            ),
            ("setElementRayleighDampingFactors", "Rayleigh factors for one element.", CUSTOM),
            ("setNodeTemperature", "Temperature of a node (thermal analysis).", CUSTOM),
            ("InitialStateAnalysis / updateMaterialStage", "Geotechnical staging.", OUT),
            ("database / save / restore", "Save and restore the domain state.", OUT),
            (
                "convertBinaryToText / convertTextToBinary / stripXML",
                "Recorder file conversions.",
                OUT,
            ),
            (
                "reset / start / stop / setPrecision / setNumThreads / getNumThreads / sdfResponse / updateElementDomain",
                "Interpreter, timing and SDOF helpers.",
                CUSTOM,
            ),
        ),
    ),
    "annex.other": (
        "Annex J — other command families",
        "FSI and PFEM, sensitivity, reliability, parallel, preprocessing, postprocessing.",
        "These chapters of the manual serve research workflows rather than structural design.",
        (
            (
                "mesh / remesh / PFEM integrator, SOE, test and analysis",
                "Fluid-structure interaction with the particle finite element method.",
                OUT,
            ),
            (
                "parameter / addToParameter / updateParameter / setParameter / getParamTags / getParamValue",
                "Parameters of a sensitivity analysis.",
                OUT,
            ),
            (
                "computeGradients / sensitivityAlgorithm / sensNodeDisp / sensNodeVel / sensNodeAccel / sensLambda / sensSectionForce / sensNodePressure",
                "Sensitivity (DDM) results.",
                OUT,
            ),
            ("randomVariable", "Random variables of a reliability analysis.", OUT),
            (
                "getPID / getNP / barrier / send / recv / Bcast / setStartNodeTag / domainChange / partition",
                "Parallel interpreters (OpenSeesMP / SP).",
                OUT,
            ),
            ("DiscretizeMember", "Splits a member into several elements.", "Edit → Mesh"),
            (
                "Postprocessing modules (opsvis, vfo)",
                "Plotting libraries for scripts.",
                "the application's own views (Display menu)",
            ),
        ),
    ),
}


def _body(intro: str, entries: tuple[tuple[str, str, str], ...]) -> str:
    lines = [intro, "", "# Commands"]
    lines += [f"- **{name}** — {what} **In the app:** {where}." for name, what, where in entries]
    lines += [
        "",
        "# Legend",
        f"- **{AUTO}** — nothing to type: the model already says it.",
        f"- **{CUSTOM}** — no form yet; write the OpenSeesPy call in a custom block.",
        f"- **{OUT}**.",
        "",
        "Arguments and options: the OpenSeesPy manual, openseespydoc.readthedocs.io.",
    ]
    return "\n".join(lines)


#: The glossary pages plus the annex index, as ``(id, title, group, summary, body, see_also)``.
GLOSSARY_GROUP = "Annex — OpenSees commands"


def glossary_pages() -> list[tuple[str, str, str, str, tuple[str, ...]]]:
    """``(id, title, summary, body, see_also)`` of every annex page, index first."""
    ids = list(_PAGES)
    index_body = "\n".join(
        [
            "This annex lists every command of the OpenSeesPy manual, family by family, "
            "with one line on what it does and where it lives in OpenSees Studio.",
            "",
            "# How to use it",
            "- Find the command you know from a script or a paper, then follow **In the app**.",
            "- A menu path means there is a form: use it, the model stays checked and exportable.",
            "- **automatic** means the application writes it from your model: a node is "
            "drawn, not typed.",
            f"- **{CUSTOM}** means no form yet: a custom block runs the call while the model "
            "is built, with its own tag range.",
            "- **outside the scope** marks research families (parallel computing, PFEM, "
            "sensitivity, reliability).",
            "",
            "# Pages",
            *(f"- **{_PAGES[i][0]}** — {_PAGES[i][1]}" for i in ids),
        ]
    )
    pages = [
        (
            "annex.index",
            "Annex — glossary of OpenSees commands",
            "Every OpenSeesPy command, what it does, and where to find it in the application.",
            index_body,
            tuple(ids),
        )
    ]
    for page_id, (title, summary, intro, entries) in _PAGES.items():
        pages.append(
            (
                page_id,
                title,
                summary,
                _body(intro, entries),
                ("annex.index", "define.custom_commands"),
            )
        )
    return pages


def command_count() -> int:
    """How many command entries the glossary holds (a row may name several aliases)."""
    return sum(len(entries) for (_t, _s, _i, entries) in _PAGES.values())
