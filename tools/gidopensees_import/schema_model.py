"""
Pydantic v2 intermediate representation for GiD schema files (.mat / .cnd).

Each parsed MATERIAL or CONDITION block becomes an EntrySpec.  Fields within a
block become FieldSpec objects.  DEPENDENCIES lines are normalised into
DependencyRule / DependencyAction objects.  The final output is a CatalogSpec
(serialisable to JSON via model_dump_json()).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DependencyAction(BaseModel):
    """One action inside a DEPENDENCIES rule: RESTORE, HIDE, or SET a field."""

    action: Literal["RESTORE", "HIDE", "SET"]
    field: str
    target: str  # "#CURRENT#" or a literal value


class DependencyRule(BaseModel):
    """A complete DEPENDENCIES clause: when trigger matches, apply actions."""

    trigger: str
    actions: list[DependencyAction]


class FieldSpec(BaseModel):
    """One QUESTION block inside a MATERIAL or CONDITION entry."""

    name: str
    widget_type: Literal["CB", "UNITS", "MAT", "SCALAR", "TUPLE"]
    options: list[str] = Field(default_factory=list)
    default: str = ""
    width_hint: int | None = None
    help_text: str = ""
    image: str = ""
    state: str | None = None  # "HIDDEN" | "DISABLED" | None
    tkwidgets: list[str] = Field(default_factory=list)
    dependencies: list[DependencyRule] = Field(default_factory=list)
    section_title: str | None = None  # enclosing TITLE: context


class EntrySpec(BaseModel):
    """One MATERIAL or CONDITION block."""

    name: str
    book: str
    source_type: Literal["MATERIAL", "CONDITION"]
    comment: str = ""
    image: str = ""
    tkwidgets: list[str] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(default_factory=list)
    condtype: str = ""       # CONDITION-only: CONDTYPE value
    condmeshtype: str = ""   # CONDITION-only: CONDMESHTYPE value


class BookSpec(BaseModel):
    """A BOOK section grouping related entries."""

    name: str
    source: Literal["mat", "cnd"]
    entries: list[EntrySpec] = Field(default_factory=list)


class CatalogSpec(BaseModel):
    """Top-level output: all books from the .mat and .cnd files."""

    mat_books: list[BookSpec] = Field(default_factory=list)
    cnd_books: list[BookSpec] = Field(default_factory=list)
