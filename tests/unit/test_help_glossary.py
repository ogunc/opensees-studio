"""The help annex names every family of the OpenSeesPy manual and says where each command is."""

from __future__ import annotations

import pytest

from opensees_studio.core.help import ACTION_TOPICS, TOPICS
from opensees_studio.core.help_glossary import CUSTOM, GLOSSARY_GROUP, command_count, glossary_pages

TEXT = " ".join(body for _i, _t, _s, body, _a in glossary_pages())

# A sample from every chapter of the manual (model, elements, materials, sections,
# loads, analysis, output, utility, research families).
COMMANDS = (
    "model",
    "node",
    "fix",
    "equalDOF",
    "rigidDiaphragm",
    "rigidLink",
    "mass",
    "region",
    "rayleigh",
    "block2D",
    "geomTransf PDelta",
    "Lobatto",
    "HingeRadau",
    "Coulomb",
    "zeroLength",
    "zeroLengthSection",
    "Truss",
    "elasticBeamColumn",
    "forceBeamColumn",
    "beamWithHinges",
    "MVLEM",
    "twoNodeLink",
    "TripleFrictionPendulum",
    "ShellMITC4",
    "ShellDKGQ",
    "tri31",
    "stdBrick",
    "SSPquad",
    "CatenaryCable",
    "Steel02",
    "Steel4",
    "Concrete04",
    "Concrete07",
    "Hysteretic",
    "ModIMKPeakOriented",
    "Pinching4",
    "ViscousDamper",
    "MinMax",
    "PySimple1",
    "ElasticIsotropic",
    "J2Plasticity",
    "PlateRebar",
    "PM4Sand",
    "Fiber",
    "LayeredShell",
    "Aggregator",
    "timeSeries Path",
    "Pulse",
    "UniformExcitation",
    "MultipleSupport",
    "eleLoad",
    "constraints",
    "numberer",
    "SparseSYM",
    "Mumps",
    "NormDispIncr",
    "RelativeEnergyIncr",
    "FixedNumIter",
    "NewtonLineSearch",
    "GeneralizedAlpha",
    "ExplicitDifference",
    "eigen",
    "analyze",
    "modalProperties",
    "responseSpectrumAnalysis",
    "nodeDisp",
    "eleResponse",
    "recorder",
    "sectionForce",
    "printA",
    "wipe",
    "loadConst",
    "remove",
    "setNodeDisp",
    "InitialStateAnalysis",
    "parameter",
    "randomVariable",
    "partition",
    "DiscretizeMember",
)


@pytest.mark.parametrize("command", COMMANDS)
def test_the_annex_names_it(command: str) -> None:
    assert command in TEXT


def test_every_entry_says_where_it_is() -> None:
    for page_id, _title, _summary, body, _also in glossary_pages():
        if page_id == "annex.index":
            continue
        commands = body.split("# Commands", 1)[1].split("# Legend", 1)[0]
        entries = [line for line in commands.splitlines() if line.startswith("- **")]
        assert entries and all("**In the app:**" in line for line in entries), page_id


def test_the_annex_is_reachable_and_large() -> None:
    pages = [i for i, *_ in glossary_pages()]
    assert all(TOPICS[i].group == GLOSSARY_GROUP for i in pages)
    assert "annex.index" in TOPICS["index"].see_also
    assert command_count() > 150
    assert CUSTOM in TEXT
    assert "define.custom_commands" in ACTION_TOPICS.values()
