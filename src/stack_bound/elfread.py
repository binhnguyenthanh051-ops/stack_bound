"""Read the linked ELF: the function inventory, DWARF declaration sites, and the address-taken set.

The ELF is the referee (ADR-0001 D1): every function comes from its symbol table, keyed by address.
"""
from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

from stack_bound.errors import AnalysisError


@dataclass
class Function:
    addr: int                   # Thumb bit cleared
    size: int
    name: str
    is_global: bool
    decl: tuple[str, int, int] | None = None     # (file basename, line, column) from DWARF
    frame: int | None = None                      # bytes, from a witness or an annotation
    frame_source: str = ""


@dataclass
class Image:
    path: Path
    sha256: str
    compiler: str
    functions: dict[int, Function] = field(default_factory=dict)      # addr -> function
    objects: dict[str, int] = field(default_factory=dict)             # data symbol -> size
    address_taken: set[int] = field(default_factory=set)

    def by_name(self, name: str) -> list[Function]:
        return [f for f in self.functions.values() if f.name == name]

    def by_decl(self, base: str, line: int, col: int, name: str) -> list[Function]:
        return [f for f in self.functions.values() if f.decl == (base, line, col) and f.name == name]


def load(path: Path) -> Image:
    """Load an unstripped ELF with DWARF, or refuse with what is missing."""
    # @impl REQ-SB-001 : refuse an ELF with no symbol table or no DWARF, naming what is missing
    # @impl REQ-SB-002 : every STT_FUNC symbol is in the inventory
    # (part of REQ-SB-003: functions keyed by address, Thumb bit cleared)
    data = path.read_bytes()
    with path.open("rb") as fh:
        elf = ELFFile(fh)
        symtab = elf.get_section_by_name(".symtab")
        missing = []
        if not isinstance(symtab, SymbolTableSection):
            missing.append("no symbol table (.symtab): the ELF is stripped")
        if not elf.has_dwarf_info() or elf.get_section_by_name(".debug_info") is None:
            missing.append("no DWARF (.debug_info): build with -g")
        if missing:
            raise AnalysisError([f"{path.name}: {m}" for m in missing])

        image = Image(path=path, sha256=hashlib.sha256(data).hexdigest(), compiler=_compiler(elf))
        for sym in symtab.iter_symbols():
            kind = sym["st_info"]["type"]
            if sym["st_shndx"] == "SHN_UNDEF" or not sym.name:
                continue
            if kind == "STT_FUNC":
                addr = sym["st_value"] & ~1
                image.functions.setdefault(addr, Function(
                    addr=addr, size=sym["st_size"], name=sym.name,
                    is_global=sym["st_info"]["bind"] in ("STB_GLOBAL", "STB_WEAK")))
            elif kind == "STT_OBJECT":
                image.objects[sym.name] = sym["st_size"]
        _attach_decls(elf, image)
        image.address_taken = _address_taken(elf, image)
    return image


def _compiler(elf: ELFFile) -> str:
    sec = elf.get_section_by_name(".comment")
    if sec is None:
        return "unknown"
    text = sec.data().split(b"\x00")
    return next((t.decode("ascii", "replace") for t in text if t.startswith(b"GCC")), "unknown")


def _attach_decls(elf: ELFFile, image: Image) -> None:
    """Give every function its DWARF declaration site, the join key for compiler data."""
    dwarf = elf.get_dwarf_info()
    for cu in dwarf.iter_CUs():
        lineprog = dwarf.line_program_for_CU(cu)
        files = _file_table(lineprog)
        for die in cu.iter_DIEs():
            if die.tag != "DW_TAG_subprogram" or "DW_AT_low_pc" not in die.attributes:
                continue
            addr = die.attributes["DW_AT_low_pc"].value & ~1
            fn = image.functions.get(addr)
            if fn is None or "DW_AT_decl_line" not in die.attributes:
                continue
            fidx = die.attributes.get("DW_AT_decl_file")
            fname = files.get(fidx.value, "") if fidx is not None else ""
            col = die.attributes["DW_AT_decl_column"].value if "DW_AT_decl_column" in die.attributes else 0
            fn.decl = (os.path.basename(fname), die.attributes["DW_AT_decl_line"].value, col)


def _file_table(lineprog) -> dict[int, str]:
    if lineprog is None:
        return {}
    entries = lineprog["file_entry"]
    version = lineprog["version"]
    base = 0 if version >= 5 else 1             # DWARF 5 file indices start at 0
    out = {}
    for i, e in enumerate(entries):
        name = e.name.decode() if isinstance(e.name, bytes) else str(e.name)
        out[i + base] = name
    return out


def _address_taken(elf: ELFFile, image: Image) -> set[int]:
    """Functions whose address (Thumb bit set) appears as an aligned word in any loaded section.

    Covers const tables (.rodata), initialised data (.data) and literal pools in code.
    """
    # (part of REQ-SB-104: data words and literal pools; movw/movt and adr come with the binary witness)
    starts = set(image.functions)
    taken: set[int] = set()
    for sec in elf.iter_sections():
        if sec["sh_type"] != "SHT_PROGBITS" or not (sec["sh_flags"] & 0x2):     # SHF_ALLOC
            continue
        raw = sec.data()
        for off in range(0, len(raw) - 3, 4):
            (word,) = struct.unpack_from("<I", raw, off)
            if word & 1 and (word & ~1) in starts:
                taken.add(word & ~1)
    return taken
