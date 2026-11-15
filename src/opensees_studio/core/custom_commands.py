"""Custom OpenSees commands: Python blocks the runner executes while it builds the model.

For anything OpenSees offers that the application has no form for yet (an
element, a material, a recorder, a constraint), the engineer writes the
OpenSeesPy calls in a block. The runner executes each *enabled* block at its
stage with these names available:

* ``ops`` — the OpenSees module the model is being built in;
* ``project`` — the :class:`~opensees_studio.core.Project` (read it, do not change it);
* ``ndm``, ``ndf`` — the model's dimensions;
* ``tag`` — the first free tag of this block (``CUSTOM_TAG_BASE`` plus 1000 per
  block), so its objects never collide with the ones the application emits.

Stages: ``after_materials`` (materials exist, nothing uses them yet),
``after_elements`` (the whole model exists, before any pattern or analysis).

A block runs only when it is enabled. Opening a project from a file disables
every block until the user trusts them (the code runs on this computer), see
``ProjectViewModel.open``. Outside the GUI the analysis CLI and the batch
refuse a project with enabled blocks unless ``--allow-custom-commands`` says
the files are trusted (:func:`untrusted_blocks_message`). The blocks are saved
with the project; a project without blocks saves byte-identical to before.

No Qt, no OpenSees.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import Field

from opensees_studio.core._base import Entity

CUSTOM_TAG_BASE = 1_000_000
"""Tags from here up are left to custom blocks: 1000 per block, in list order."""

CustomStage = Literal["after_materials", "after_elements"]
STAGE_LABELS: dict[str, str] = {
    "after_materials": "After the materials (before sections and elements)",
    "after_elements": "After the elements (the whole model, before loads and analysis)",
}


class CustomCommandBlock(Entity):
    """A named block of OpenSeesPy calls run at one stage of the model build."""

    stage: CustomStage = "after_elements"
    code: str = Field(default="", description="Python source; ``ops`` is OpenSeesPy.")
    enabled: bool = True


def block_tag_base(index: int) -> int:
    """The first tag the block at ``index`` (0-based, in project order) may use."""
    return CUSTOM_TAG_BASE + 1000 * index


def enabled_blocks(blocks: Iterable[CustomCommandBlock]) -> list[CustomCommandBlock]:
    """The blocks that would run: enabled and not empty."""
    return [b for b in blocks if b.enabled and b.code.strip()]


def untrusted_blocks_message(blocks: Iterable[CustomCommandBlock]) -> str:
    """Why a project with enabled blocks is refused outside the GUI."""
    found = list(blocks)
    names = ", ".join(b.name or str(b.id) for b in found)
    return (
        f"The project has {len(found)} enabled custom Python block(s) ({names}), which "
        "run on this computer. They run only with --allow-custom-commands: give it "
        "for files you trust, or disable the blocks in Define → Custom OpenSees Commands."
    )
