"""The newest glibc a Linux bundle needs, and a gate on it.

A program linked on one Linux runs on another only if that one's glibc is at
least as new as every ``GLIBC_x.y`` symbol version the program's binaries ask
for. The bundle carries its own Python, Qt and VTK, but never glibc: it takes
the system's. Built on Ubuntu 24.04 it asked for glibc 2.38 and up, and Linux
Mint 21 (Ubuntu 22.04, glibc 2.35) refused to start it.

This script reads the dynamic symbol table of every ELF file in the bundle with
``objdump -T`` and reports the newest ``GLIBC_`` version required, file by file;
with ``--max`` it fails when one asks for more::

    python tools/glibc_floor.py dist/OpenSeesStudio --max 2.35

2.35 is the glibc of Ubuntu 22.04 and Linux Mint 21, the oldest base the
release supports (Debian 12 and LMDE 6 have 2.36).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
_GLIBC = re.compile(r"\bGLIBC_(\d+)\.(\d+)(?:\.(\d+))?\b")

Version = tuple[int, int, int]


def parse_version(text: str) -> Version:
    """``"2.35"`` → ``(2, 35, 0)``."""
    parts = [int(p) for p in text.split(".")]
    return (parts[0], parts[1], parts[2] if len(parts) > 2 else 0)


def show(version: Version) -> str:
    return ".".join(str(v) for v in (version if version[2] else version[:2]))


def required_glibc(objdump_output: str) -> Version | None:
    """The newest ``GLIBC_`` symbol version in ``objdump -T`` output, None without one."""
    found = [
        (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
        for m in _GLIBC.finditer(objdump_output)
    ]
    return max(found) if found else None


def elf_files(root: Path) -> list[Path]:
    """Every regular ELF file under ``root`` (executables and shared libraries)."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            with path.open("rb") as handle:
                if handle.read(4) == ELF_MAGIC:
                    out.append(path)
        except OSError:
            continue
    return out


def scan(root: Path) -> dict[Path, Version]:
    """ELF file → the newest glibc it asks for (files asking for none are left out)."""
    out: dict[Path, Version] = {}
    for path in elf_files(root):
        proc = subprocess.run(
            ["objdump", "-T", str(path)], capture_output=True, text=True, check=False
        )
        version = required_glibc(proc.stdout)
        if version is not None:
            out[path] = version
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path, help="the unpacked bundle folder")
    parser.add_argument("--max", type=parse_version, help="fail above this glibc, e.g. 2.35")
    parser.add_argument("--top", type=int, default=10, help="files to list, newest first")
    args = parser.parse_args(argv)
    if not args.bundle.is_dir():
        print(f"{args.bundle} is not a folder.", file=sys.stderr)
        return 2
    needs = scan(args.bundle)
    if not needs:
        print("No ELF file asks for a glibc symbol version (is objdump installed?).")
        return 2 if args.max else 0
    newest = max(needs.values())
    print(f"{len(needs)} ELF file(s); the bundle needs glibc {show(newest)} or newer.")
    for path, version in sorted(needs.items(), key=lambda kv: kv[1], reverse=True)[: args.top]:
        print(f"  {show(version):>6}  {path.relative_to(args.bundle)}")
    if args.max is not None and newest > args.max:
        over = [p for p, v in needs.items() if v > args.max]
        print(
            f"::error::{len(over)} file(s) need glibc newer than {show(args.max)}: the bundle "
            "would not start on the oldest supported Linux. Build on an older base.",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
