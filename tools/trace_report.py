"""trace_report.py -- stack_bound's own traceability check.

Reads:
    docs/requirements/*.md   requirement rows: "| REQ-XX-NNN | text | ADR-NNNN Dn, ... | ... |"
    docs/adr/ADR-*.md        ADR id, title, status ("**Status:** <word>"), decisions ("### Dn.")
    src/, tests/, tools/     impl/test tags in source comments (see docs/traceability-convention.md)

Writes docs/traceability.md (generated, committed). With --check, writes nothing and fails if the
committed file is stale.

Gaps (exit 1):
    duplicate-req   the same requirement ID defined twice
    no-trace        a requirement with no "ADR-NNNN Dn" reference
    bad-trace       a requirement tracing to an ADR or decision that doesn't exist
    dangling        a tag naming an ID that doesn't exist
    uncovered       a requirement in a *gated* area, tracing to an accepted ADR, with no impl
                    or no test tag

Requirement states:
    covered   has an impl and a test tag
    open      its ADR is accepted, but it isn't implemented and tested yet
    pending   its ADRs are all still proposed

Accepting an ADR means the design is decided, not that it is built. Coverage is enforced per area
through the gates in pyproject.toml ([tool.trace_report] gates = ["REQ-SB-1", ...]): an "open"
requirement whose ID starts with a gate prefix is a gap. Add a gate when an area is implemented.
"""
from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

AT = "@"  # kept apart so this file never matches its own tag pattern
ID_RE = r"(?:ADR-\d{4}(?: D\d+)?|REQ-[A-Z]+-\d{3})"
TAG_RE = re.compile(AT + r"(impl|test)\s+(" + ID_RE + r")")
REQ_ROW_RE = re.compile(r"^\|\s*(REQ-[A-Z]+-\d{3})\s*\|(.*)$")
TRACE_RE = re.compile(r"(ADR-\d{4})\s+(D\d+)")
ADR_FILE_RE = re.compile(r"^(ADR-\d{4})-.*\.md$")
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*([A-Za-z]+)", re.M)
TITLE_RE = re.compile(r"^#\s+ADR-\d{4}:\s*(.+)$", re.M)
DECISION_RE = re.compile(r"^###\s+(D\d+)\.", re.M)

REQ_DIR = Path("docs") / "requirements"
ADR_DIR = Path("docs") / "adr"
OUT_PATH = Path("docs") / "traceability.md"
SCAN_DIRS = ("src", "tests", "tools")
SCAN_SUFFIXES = {".py", ".c", ".h", ".cpp", ".hpp", ".s", ".S"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", "build", "dist"}


@dataclass
class Req:
    rid: str
    text: str
    traces: list[tuple[str, str]]
    source: str


@dataclass
class Adr:
    aid: str
    title: str
    status: str
    decisions: set[str]


@dataclass
class Tag:
    kind: str   # "impl" | "test"
    target: str
    where: str  # "path:line"


@dataclass
class Model:
    reqs: dict[str, Req] = field(default_factory=dict)
    adrs: dict[str, Adr] = field(default_factory=dict)
    tags: list[Tag] = field(default_factory=list)
    gates: list[str] = field(default_factory=list)  # requirement-ID prefixes whose coverage is enforced
    gaps: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, id, detail)


def load_gates(root: Path) -> list[str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return []
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return sorted(data.get("tool", {}).get("trace_report", {}).get("gates", []))


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _split_row(rest: str) -> list[str]:
    return [c.strip() for c in rest.strip().rstrip("|").split("|")]


def parse_adrs(root: Path, model: Model) -> None:
    adr_dir = root / ADR_DIR
    for path in sorted(adr_dir.glob("ADR-*.md")) if adr_dir.is_dir() else []:
        m = ADR_FILE_RE.match(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8")
        status = STATUS_RE.search(text)
        title = TITLE_RE.search(text)
        model.adrs[m.group(1)] = Adr(
            aid=m.group(1),
            title=title.group(1).strip() if title else "",
            status=status.group(1).lower() if status else "unknown",
            decisions=set(DECISION_RE.findall(text)),
        )


def parse_requirements(root: Path, model: Model) -> None:
    req_dir = root / REQ_DIR
    for path in sorted(req_dir.glob("*.md")) if req_dir.is_dir() else []:
        rel = _rel(root, path)
        for line in path.read_text(encoding="utf-8").splitlines():
            m = REQ_ROW_RE.match(line)
            if not m:
                continue
            rid = m.group(1)
            cells = _split_row(m.group(2))
            text = cells[0] if cells else ""
            traces = TRACE_RE.findall(cells[1]) if len(cells) > 1 else []
            if rid in model.reqs:
                model.gaps.append(("duplicate-req", rid, f"{rel} and {model.reqs[rid].source}"))
                continue
            model.reqs[rid] = Req(rid, text, traces, rel)


def scan_tags(root: Path, model: Model) -> None:
    for top in SCAN_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if SKIP_PARTS.intersection(path.relative_to(root).parts):
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for n, line in enumerate(lines, start=1):
                for kind, target in TAG_RE.findall(line):
                    model.tags.append(Tag(kind, target, f"{_rel(root, path)}:{n}"))


def _id_exists(model: Model, target: str) -> bool:
    if target.startswith("REQ-"):
        return target in model.reqs
    aid, _, dec = target.partition(" ")
    adr = model.adrs.get(aid)
    return adr is not None and (not dec or dec in adr.decisions)


def check(model: Model) -> None:
    for req in model.reqs.values():
        if not req.traces:
            model.gaps.append(("no-trace", req.rid, "no 'ADR-NNNN Dn' in the Traces column"))
        for aid, dec in req.traces:
            adr = model.adrs.get(aid)
            if adr is None or dec not in adr.decisions:
                model.gaps.append(("bad-trace", req.rid, f"{aid} {dec} does not exist"))
    for tag in model.tags:
        if not _id_exists(model, tag.target):
            model.gaps.append(("dangling", tag.target, tag.where))
    for req in model.reqs.values():
        gated = any(req.rid.startswith(g) for g in model.gates)
        if gated and state_of(model, req) == "open":
            missing = [k for k in ("impl", "test") if not tags_for(model, req.rid, k)]
            model.gaps.append(("uncovered", req.rid, "gated, missing " + " and ".join(missing)))


def tags_for(model: Model, rid: str, kind: str) -> list[Tag]:
    return [t for t in model.tags if t.kind == kind and t.target == rid]


def state_of(model: Model, req: Req) -> str:
    has_impl = bool(tags_for(model, req.rid, "impl"))
    has_test = bool(tags_for(model, req.rid, "test"))
    if has_impl and has_test:
        return "covered"
    accepted = any(model.adrs.get(a) and model.adrs[a].status == "accepted" for a, _ in req.traces)
    return "open" if accepted else "pending"


def build_model(root: Path) -> Model:
    model = Model(gates=load_gates(root))
    parse_adrs(root, model)
    parse_requirements(root, model)
    scan_tags(root, model)
    check(model)
    model.gaps.sort()
    return model


def _files(tags: list[Tag]) -> str:
    files = sorted({t.where.rsplit(":", 1)[0] for t in tags})
    return "<br>".join(f"`{f}`" for f in files) if files else "—"


def render(model: Model) -> str:
    states = [state_of(model, r) for r in model.reqs.values()]
    out = [
        "# Traceability matrix",
        "",
        "> Generated by `tools/trace_report.py`. Do not edit by hand. "
        "Convention: [traceability-convention.md](traceability-convention.md).",
        "",
        f"{len(model.reqs)} requirements · {states.count('covered')} covered · "
        f"{states.count('open')} open (accepted, not built yet) · "
        f"{states.count('pending')} pending (decision not yet accepted) · "
        f"{len(model.tags)} tags · {len(model.gaps)} gaps",
        "",
        "Coverage enforced for: " + (", ".join(f"`{g}*`" for g in model.gates) or "no area yet")
        + " (gates in `pyproject.toml`, `[tool.trace_report]`).",
        "",
        "## Decisions",
        "",
        "| ADR | Title | Status | Decisions | Tags |",
        "|---|---|---|---|---|",
    ]
    for adr in sorted(model.adrs.values(), key=lambda a: a.aid):
        n_tags = sum(1 for t in model.tags if t.target.split(" ")[0] == adr.aid)
        out.append(f"| {adr.aid} | {adr.title} | {adr.status} | {len(adr.decisions)} | {n_tags} |")
    out += [
        "",
        "## Requirements",
        "",
        "| Requirement | Traces | impl | test | State |",
        "|---|---|---|---|---|",
    ]
    for req in sorted(model.reqs.values(), key=lambda r: r.rid):
        traces = ", ".join(f"{a} {d}" for a, d in req.traces) or "—"
        out.append(
            f"| {req.rid} | {traces} | {_files(tags_for(model, req.rid, 'impl'))} | "
            f"{_files(tags_for(model, req.rid, 'test'))} | {state_of(model, req)} |"
        )
    out += ["", "## Gaps", ""]
    if model.gaps:
        out += ["| Kind | ID | Detail |", "|---|---|---|"]
        out += [f"| {k} | {i} | {d} |" for k, i, d in model.gaps]
    else:
        out.append("None.")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--check", action="store_true",
                    help="write nothing; fail if docs/traceability.md is stale")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    model = build_model(root)
    text = render(model)
    out = root / OUT_PATH
    rc = 0
    if args.check:
        current = out.read_text(encoding="utf-8") if out.is_file() else ""
        if current != text:
            print(f"stale: {OUT_PATH.as_posix()} (run tools/trace_report.py)", file=sys.stderr)
            rc = 1
    else:
        out.write_text(text, encoding="utf-8", newline="\n")
    for kind, rid, detail in model.gaps:
        print(f"gap: {kind}: {rid}: {detail}", file=sys.stderr)
    print(f"{len(model.reqs)} requirements, {len(model.tags)} tags, {len(model.gaps)} gaps")
    return 1 if model.gaps else rc


if __name__ == "__main__":
    sys.exit(main())
