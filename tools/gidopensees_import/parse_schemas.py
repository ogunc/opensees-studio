"""
Parser for GiD schema files (OpenSees.mat, OpenSees.cnd).

CLI usage:
    python -m tools.gidopensees_import.parse_schemas \\
        --mat path/to/OpenSees.mat \\
        --cnd path/to/OpenSees.cnd \\
        --out tools/gidopensees_import/schemas.json

The parser is tolerant of CRLF line endings, blank lines, and leading
whitespace.  It fails loudly (ParseError with file + line number) on any
structurally malformed input.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from tools.gidopensees_import.schema_model import (
    BookSpec,
    CatalogSpec,
    DependencyAction,
    DependencyRule,
    EntrySpec,
    FieldSpec,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised on unrecoverable parse failure; carries file + line context."""

    def __init__(self, msg: str, path: Path, lineno: int) -> None:
        super().__init__(f"{path}:{lineno}: {msg}")
        self.path = path
        self.lineno = lineno


# ---------------------------------------------------------------------------
# QUESTION-line parser helpers
# ---------------------------------------------------------------------------

_WIDGET_RE = re.compile(
    r"""^(?P<name>[^#(]+?)   # field name (greedy up to first # or ()
        (?:
            \#(?P<wtype>CB|UNITS|MAT)\#  # widget type marker
            (?:\((?P<opts>[^)]*)\))?     # optional (options…)
        |
            \((?P<tuple_opts>[^)]*)\)    # bare tuple: Name(sub1,sub2,…)
        )?
        \s*$
    """,
    re.VERBOSE,
)


def _parse_question(text: str) -> tuple[str, str, list[str]]:
    """Return (normalized_name, widget_type, options) from a QUESTION value.

    widget_type is one of: "CB", "UNITS", "MAT", "SCALAR", "TUPLE".
    """
    m = _WIDGET_RE.match(text.strip())
    if not m:
        # Fall back to treating the whole string as a plain scalar name
        return text.strip().rstrip(":").strip(), "SCALAR", []

    raw_name = m.group("name").strip().rstrip(":").strip()
    wtype = m.group("wtype")
    opts_str = m.group("opts")
    tuple_str = m.group("tuple_opts")

    if wtype:
        options = [o.strip() for o in opts_str.split(",")] if opts_str else []
        return raw_name, wtype, options

    if tuple_str is not None:
        options = [o.strip() for o in tuple_str.split(",")]
        return raw_name, "TUPLE", options

    return raw_name, "SCALAR", []


# ---------------------------------------------------------------------------
# VALUE-line parser helpers
# ---------------------------------------------------------------------------

_WIDTH_RE = re.compile(r"#WIDTH#\((\d+)\)\s*$")


def _parse_value(text: str) -> tuple[str, int | None]:
    """Strip #WIDTH#(N) suffix; return (clean_value, width_hint_or_None)."""
    m = _WIDTH_RE.search(text)
    if m:
        width = int(m.group(1))
        clean = text[: m.start()].strip()
        return clean, width
    return text.strip(), None


# ---------------------------------------------------------------------------
# DEPENDENCIES parser
# ---------------------------------------------------------------------------

_DEP_GROUPS_RE = re.compile(r"\(([^)]*)\)")
_KNOWN_ACTIONS = {"RESTORE", "HIDE", "SET"}


def _parse_dep_group(content: str, path: Path, lineno: int) -> DependencyRule:
    """Parse the content inside one (…) dependency group."""
    parts = [p.strip() for p in content.split(",")]
    if not parts:
        raise ParseError("Empty DEPENDENCIES group", path, lineno)

    trigger = parts[0]
    actions: list[DependencyAction] = []
    rest = parts[1:]

    i = 0
    while i < len(rest):
        token = rest[i].upper()
        if token not in _KNOWN_ACTIONS:
            # unknown token - could be a stray value; skip gracefully
            i += 1
            continue
        if i + 2 >= len(rest):
            raise ParseError(
                f"Truncated DEPENDENCIES action near '{rest[i]}'", path, lineno
            )
        action_str = rest[i]
        fname = rest[i + 1]
        target = rest[i + 2]
        actions.append(
            DependencyAction(action=action_str.upper(), field=fname, target=target)  # type: ignore[arg-type]
        )
        i += 3

    return DependencyRule(trigger=trigger, actions=actions)


def _parse_dependencies(value: str, path: Path, lineno: int) -> list[DependencyRule]:
    """Extract all dependency groups from a DEPENDENCIES line value."""
    groups = _DEP_GROUPS_RE.findall(value)
    if not groups:
        raise ParseError(f"DEPENDENCIES line has no (...) groups: {value!r}", path, lineno)
    return [_parse_dep_group(g, path, lineno) for g in groups]


# ---------------------------------------------------------------------------
# In-progress entry builder (mutable accumulator)
# ---------------------------------------------------------------------------

_END_RE = re.compile(r"^END[\s_](?:MATERIAL|CONDITION)\s*$", re.IGNORECASE)


@dataclass
class _FieldBuilder:
    name: str
    widget_type: str
    options: list[str] = field(default_factory=list)
    default: str = ""
    width_hint: int | None = None
    help_text: str = ""
    image: str = ""
    state: str | None = None
    tkwidgets: list[str] = field(default_factory=list)
    dependencies: list[DependencyRule] = field(default_factory=list)
    section_title: str | None = None

    def build(self) -> FieldSpec:
        return FieldSpec(
            name=self.name,
            widget_type=self.widget_type,  # type: ignore[arg-type]
            options=self.options,
            default=self.default,
            width_hint=self.width_hint,
            help_text=self.help_text,
            image=self.image,
            state=self.state,
            tkwidgets=self.tkwidgets,
            dependencies=self.dependencies,
            section_title=self.section_title,
        )


@dataclass
class _EntryBuilder:
    name: str
    book: str
    source_type: Literal["MATERIAL", "CONDITION"]
    comment: str = ""
    image: str = ""
    tkwidgets: list[str] = field(default_factory=list)
    condtype: str = ""
    condmeshtype: str = ""
    fields: list[FieldSpec] = field(default_factory=list)
    _current_field: _FieldBuilder | None = field(default=None, repr=False)
    _section_title: str | None = field(default=None, repr=False)

    def open_field(self, name: str, widget_type: str, options: list[str]) -> None:
        self._flush_field()
        self._current_field = _FieldBuilder(
            name=name,
            widget_type=widget_type,
            options=options,
            section_title=self._section_title,
        )

    def _flush_field(self) -> None:
        if self._current_field is not None:
            self.fields.append(self._current_field.build())
            self._current_field = None

    def finish(self) -> EntrySpec:
        self._flush_field()
        return EntrySpec(
            name=self.name,
            book=self.book,
            source_type=self.source_type,
            comment=self.comment,
            image=self.image,
            tkwidgets=self.tkwidgets,
            fields=self.fields,
            condtype=self.condtype,
            condmeshtype=self.condmeshtype,
        )


# ---------------------------------------------------------------------------
# Core file parser
# ---------------------------------------------------------------------------


def _parse_file(path: Path, source: Literal["mat", "cnd"]) -> list[BookSpec]:
    """Parse one .mat or .cnd file; return the list of BookSpec objects."""
    source_type_for_entry: Literal["MATERIAL", "CONDITION"] = (
        "MATERIAL" if source == "mat" else "CONDITION"
    )
    entry_keyword = "MATERIAL" if source == "mat" else "CONDITION"

    raw = path.read_bytes()
    # Normalise CRLF → LF; decode as UTF-8 with latin-1 fallback
    try:
        text = raw.replace(b"\r\n", b"\n").decode("utf-8")
    except UnicodeDecodeError:
        text = raw.replace(b"\r\n", b"\n").decode("latin-1")

    books: list[BookSpec] = []
    current_book: BookSpec | None = None
    current_entry: _EntryBuilder | None = None

    def _close_entry() -> None:
        nonlocal current_entry
        if current_entry is not None and current_book is not None:
            current_book.entries.append(current_entry.finish())
            current_entry = None

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        # Blank line
        if not line:
            continue

        # Pure comment lines (but NOT directives prefixed with #)
        if line.startswith("#") and not re.match(r"#\s*(?:QUESTION|VALUE|DEPENDENCIES):", line):
            # Could be a genuine comment OR a commented-out directive.
            # Either way, skip.
            continue

        # Attempt keyword:value split
        if ":" not in line:
            # No colon — cannot be a directive; skip silently
            continue

        keyword, _, rest = line.partition(":")
        keyword = keyword.strip().upper()
        value = rest.strip()

        # ── END ──────────────────────────────────────────────────────────
        if _END_RE.match(line):
            _close_entry()
            continue

        # ── BOOK ─────────────────────────────────────────────────────────
        if keyword == "BOOK":
            _close_entry()
            current_book = BookSpec(name=value, source=source)
            books.append(current_book)
            continue

        # ── MATERIAL / CONDITION ─────────────────────────────────────────
        if keyword == entry_keyword:
            if current_book is None:
                raise ParseError(
                    f"{entry_keyword}: block found before any BOOK:", path, lineno
                )
            _close_entry()
            current_entry = _EntryBuilder(
                name=value,
                book=current_book.name,
                source_type=source_type_for_entry,
            )
            continue

        # Everything below requires an active entry
        if current_entry is None:
            continue

        cf = current_entry._current_field

        # ── CONDTYPE / CONDMESHTYPE ───────────────────────────────────────
        if keyword == "CONDTYPE":
            current_entry.condtype = value
            continue
        if keyword == "CONDMESHTYPE":
            current_entry.condmeshtype = value
            continue

        # ── COMMENT ──────────────────────────────────────────────────────
        if keyword == "COMMENT":
            current_entry.comment = value
            continue

        # ── TITLE ────────────────────────────────────────────────────────
        if keyword == "TITLE":
            current_entry._section_title = value
            continue

        # ── QUESTION ─────────────────────────────────────────────────────
        if keyword == "QUESTION":
            name, wtype, options = _parse_question(value)
            current_entry.open_field(name, wtype, options)
            continue

        # ── VALUE ────────────────────────────────────────────────────────
        if keyword == "VALUE":
            if cf is None:
                # VALUE before any QUESTION in entry — ignore
                continue
            clean, width = _parse_value(value)
            cf.default = clean
            if width is not None:
                cf.width_hint = width
            continue

        # ── HELP ─────────────────────────────────────────────────────────
        if keyword == "HELP":
            if cf is not None:
                cf.help_text = value
            continue

        # ── IMAGE ────────────────────────────────────────────────────────
        if keyword == "IMAGE":
            if cf is not None:
                cf.image = value
            else:
                current_entry.image = value
            continue

        # ── STATE ────────────────────────────────────────────────────────
        if keyword == "STATE":
            if cf is not None:
                cf.state = value.upper()
            continue

        # ── TKWIDGET ─────────────────────────────────────────────────────
        if keyword == "TKWIDGET":
            if cf is not None:
                cf.tkwidgets.append(value)
            else:
                current_entry.tkwidgets.append(value)
            continue

        # ── DEPENDENCIES ─────────────────────────────────────────────────
        if keyword == "DEPENDENCIES":
            if cf is None:
                # DEPENDENCIES before first QUESTION — unusual, skip
                continue
            try:
                rules = _parse_dependencies(value, path, lineno)
            except ParseError:
                raise
            except Exception as exc:
                raise ParseError(str(exc), path, lineno) from exc
            cf.dependencies.extend(rules)
            continue

        # Unknown keyword — silently ignore (forward-compatible)

    # Close any entry that was open at EOF (no explicit END)
    _close_entry()

    return books


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_mat(mat_path: Path) -> list[BookSpec]:
    return _parse_file(mat_path, "mat")


def parse_cnd(cnd_path: Path) -> list[BookSpec]:
    return _parse_file(cnd_path, "cnd")


def build_catalog(mat_path: Path, cnd_path: Path) -> CatalogSpec:
    return CatalogSpec(
        mat_books=parse_mat(mat_path),
        cnd_books=parse_cnd(cnd_path),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Parse gidopensees .mat/.cnd files into a normalised schemas.json"
    )
    parser.add_argument("--mat", required=True, type=Path, help="Path to OpenSees.mat")
    parser.add_argument("--cnd", required=True, type=Path, help="Path to OpenSees.cnd")
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output JSON file path (e.g. tools/gidopensees_import/schemas.json)",
    )
    args = parser.parse_args(argv)

    mat_path: Path = args.mat
    cnd_path: Path = args.cnd
    out_path: Path = args.out

    for p in (mat_path, cnd_path):
        if not p.exists():
            print(f"error: file not found: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"Parsing {mat_path} ...")
    catalog = build_catalog(mat_path, cnd_path)

    mat_entries = sum(len(b.entries) for b in catalog.mat_books)
    cnd_entries = sum(len(b.entries) for b in catalog.cnd_books)
    print(
        f"  .mat: {len(catalog.mat_books)} books, {mat_entries} materials\n"
        f"  .cnd: {len(catalog.cnd_books)} books, {cnd_entries} conditions"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        catalog.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"Written -> {out_path}")


if __name__ == "__main__":
    _cli()
