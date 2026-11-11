"""The GCC compiler witness: strict parsers for -fstack-usage (.su) and -fcallgraph-info (.ci).

Strict means an unknown construct is an error, never skipped (REQ-SB-501).
"""
from __future__ import annotations

from stack_bound.paths import base as path_base
import re
from dataclasses import dataclass, field
from pathlib import Path

from stack_bound.errors import AnalysisError

SU_LINE = re.compile(r"^(?P<file>.+):(?P<line>\d+):(?P<col>\d+):(?P<name>[^\t]+)\t(?P<bytes>\d+)\t(?P<qual>[a-z,]+)$")
INDIRECT = "__indirect_call"


@dataclass
class SuEntry:
    file: str           # basename
    line: int
    col: int
    name: str
    frame: int
    where: str          # "path:lineno" of the .su line, for messages


@dataclass
class CiEdge:
    source: str         # node title: "path:name" for statics, "name" for globals
    target: str
    loc: str            # call-site "file:line:col"


@dataclass
class Witness:
    frames: list[SuEntry] = field(default_factory=list)
    edges: list[CiEdge] = field(default_factory=list)


def parse_su(text: str, where: str) -> list[SuEntry]:
    # @impl REQ-SB-501 : .su lines must match the format; dynamic frames are refused, not guessed
    out = []
    for n, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        m = SU_LINE.match(raw)
        if not m:
            raise AnalysisError(f"{where}:{n}: not a -fstack-usage line: {raw!r}")
        if m["qual"] != "static":
            raise AnalysisError(f"{where}:{n}: {m['name']} has a '{m['qual']}' frame (VLA or alloca): "
                                "no static bound")
        out.append(SuEntry(path_base(m["file"]), int(m["line"]), int(m["col"]), m["name"],
                           int(m["bytes"]), f"{where}:{n}"))
    return out


_TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<word>[A-Za-z_][\w]*)|(?P<punct>[{}:]))')


def _tokens(text: str, where: str):
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            raise AnalysisError(f"{where}: unexpected text at offset {pos}: {text[pos:pos + 30]!r}")
        pos = m.end()
        if m["str"] is not None:
            yield ("str", re.sub(r'\\(["\\])', r"\1", m["str"][1:-1]))
        elif m["word"] is not None:
            yield ("word", m["word"])
        else:
            yield ("punct", m["punct"])


def parse_ci(text: str, where: str) -> list[CiEdge]:
    """Parse GCC's VCG call graph: graph: { title: ... node: {...} edge: {...} }."""
    # @impl REQ-SB-501 : a real tokenizer + grammar for .ci; unknown records are errors
    toks = list(_tokens(text, where))
    i = 0

    def expect(kind, value=None):
        nonlocal i
        if i >= len(toks) or toks[i][0] != kind or (value is not None and toks[i][1] != value):
            got = toks[i] if i < len(toks) else ("end", "")
            raise AnalysisError(f"{where}: expected {value or kind}, got {got[1]!r}")
        i += 1
        return toks[i - 1][1]

    def record() -> dict[str, str]:
        expect("punct", "{")
        fields: dict[str, str] = {}
        while toks[i] != ("punct", "}"):
            key = expect("word")
            expect("punct", ":")
            if toks[i][0] == "str":
                fields[key] = expect("str")
            else:
                fields[key] = expect("word")
        expect("punct", "}")
        return fields

    edges: list[CiEdge] = []
    expect("word", "graph")
    expect("punct", ":")
    expect("punct", "{")
    while i < len(toks) and toks[i] != ("punct", "}"):
        kind = expect("word")
        if kind == "title":
            expect("punct", ":")
            expect("str")
            continue
        if kind not in ("node", "edge"):
            raise AnalysisError(f"{where}: unknown record '{kind}' in call graph")
        expect("punct", ":")
        rec = record()
        if kind == "edge":
            for k in ("sourcename", "targetname"):
                if k not in rec:
                    raise AnalysisError(f"{where}: edge without {k}")
            edges.append(CiEdge(rec["sourcename"], rec["targetname"], rec.get("label", "")))
    expect("punct", "}")
    if i != len(toks):
        raise AnalysisError(f"{where}: text after the end of the graph")
    return edges


def load_dir(directory: Path) -> Witness:
    """Read every .su / .ci file under a directory."""
    w = Witness()
    su = sorted(directory.rglob("*.su"))
    ci = sorted(directory.rglob("*.ci"))
    if not su:
        raise AnalysisError(f"{directory}: no .su files (build with -fstack-usage -fcallgraph-info=su)")
    for p in su:
        w.frames += parse_su(p.read_text(encoding="utf-8", errors="replace"), p.name)
    for p in ci:
        w.edges += parse_ci(p.read_text(encoding="utf-8", errors="replace"), p.name)
    return w
