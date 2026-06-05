"""Pure-Python domain layer.

This package never imports Qt or openseespy. Anything in here is safe
to use from a script, a Jupyter notebook, or a future CLI.
"""

from opensees_studio.core.analysis import (
    AnalysisCase,
    ModalCase,
    PushoverCase,
    ResponseSpectrumCase,
    StaticCase,
    TransientCase,
)
from opensees_studio.core.constraints import EqualDOFConstraint
from opensees_studio.core.geometry import (
    BeamWithHingesElement,
    CoordinateGridSystem,
    CoordinateSystem,
    CorotTrussElement,
    DispBeamColumn,
    ElasticBeamColumn,
    Element,
    ForceBeamColumn,
    GridLine,
    GridSystem,
    Node,
    QuadElement,
    TrussElement,
    ZeroLengthElement,
    ZeroLengthSectionElement,
    default_global_system,
    make_grid_lines,
)
from opensees_studio.core.loads import (
    ConstantTimeSeries,
    LinearTimeSeries,
    LoadPattern,
    NodalLoad,
    PathTimeSeries,
    PlainLoadPattern,
    ResponseSpectrum,
    TimeSeries,
    UniformElementLoad,
    UniformExcitationPattern,
)
from opensees_studio.core.materials import (
    Concrete01,
    Concrete02,
    Concrete04,
    ElasticIsotropic,
    ElasticPP,
    ElasticUniaxial,
    HystereticMaterial,
    Material,
    Steel01,
    Steel02,
)
from opensees_studio.core.project import Project, ProjectMeta
from opensees_studio.core.sections import (
    AggregatorDOF,
    CircularPatch,
    ElasticSection,
    FiberSection,
    Fibre,
    RectangularPatch,
    Section,
    SectionAggregator,
    StraightLayer,
)
from opensees_studio.core.units import UnitLabels, UnitSystem, labels_for

__all__ = [
    # Project + meta
    "Project",
    "ProjectMeta",
    "UnitSystem",
    "UnitLabels",
    "labels_for",
    # Geometry
    "Node",
    "EqualDOFConstraint",
    "Element",
    "TrussElement",
    "CorotTrussElement",
    "ElasticBeamColumn",
    "ForceBeamColumn",
    "DispBeamColumn",
    "ZeroLengthElement",
    "ZeroLengthSectionElement",
    "BeamWithHingesElement",
    "QuadElement",
    "GridSystem",
    "GridLine",
    "CoordinateSystem",
    "CoordinateGridSystem",
    "default_global_system",
    "make_grid_lines",
    # Materials
    "Material",
    "ElasticIsotropic",
    "ElasticUniaxial",
    "Steel01",
    "Steel02",
    "Concrete01",
    "Concrete02",
    "Concrete04",
    "ElasticPP",
    "HystereticMaterial",
    # Sections
    "Section",
    "ElasticSection",
    "FiberSection",
    "Fibre",
    "RectangularPatch",
    "CircularPatch",
    "StraightLayer",
    "SectionAggregator",
    "AggregatorDOF",
    # Loads
    "TimeSeries",
    "LinearTimeSeries",
    "ConstantTimeSeries",
    "PathTimeSeries",
    "LoadPattern",
    "PlainLoadPattern",
    "UniformExcitationPattern",
    "NodalLoad",
    "UniformElementLoad",
    "ResponseSpectrum",
    # Analysis
    "AnalysisCase",
    "StaticCase",
    "ModalCase",
    "TransientCase",
    "PushoverCase",
    "ResponseSpectrumCase",
]
