"""Join the witnesses onto the ELF inventory, resolve function pointers, walk, and check each stack.

Slice 1: compiler witness only (GCC .su/.ci); function pointers resolved by a checked list
(tier "listed", ADR-0001 D6). Value tracking, the binary witness and the interrupt stack come later.
"""
from __future__ import annotations

import math
from stack_bound.paths import base as path_base
from dataclasses import dataclass, field

from stack_bound.elfread import Function, Image
from stack_bound.errors import AnalysisError
from stack_bound.gcc import INDIRECT, Witness
from stack_bound.project import Project


@dataclass
class Step:
    fn: Function
    via: str            # "call" | "listed: <reason>" | "" for the entry


@dataclass
class StackResult:
    entry: str
    path: list[Step]
    path_bytes: int
    switch_bytes: int
    required: int
    configured: int
    configured_from: str
    used: float
    recommended: int
    status: str         # "ok" | "FAIL" | "OVERSIZED"


@dataclass
class Graph:
    calls: dict[int, list[tuple[int, str]]] = field(default_factory=dict)      # addr -> [(callee addr, via)]
    sites: dict[int, list[str]] = field(default_factory=dict)                  # addr -> indirect call locations
    unresolved: dict[int, list[str]] = field(default_factory=dict)             # addr -> callee titles not in ELF
    listed: dict[int, tuple[list[int], str]] = field(default_factory=dict)     # addr -> (targets, reason)


def attach_frames(image: Image, witness: Witness, project: Project) -> None:
    """Compiler frames joined on DWARF (file, line, column, name); annotations for the rest."""
    # (part of REQ-SB-003: joined on DWARF (file, line, column, name); clones by name, not yet tested)
    errors = []
    for e in witness.frames:
        cands = image.by_decl(e.file, e.line, e.col, e.name)
        if not cands:
            cands = [f for f in image.by_name(e.name) if f.decl is None or f.decl[0] == e.file]
        if cands and all(f.unit for f in cands):
            # A static inline from a header has one copy per unit that emits it, all with the same
            # declaration; the .su file names the unit (foo.su <- foo.c), so keep that unit's copy.
            unit = e.where.rpartition(":")[0].removesuffix(".su")
            cands = [f for f in cands if f.unit.rpartition(".")[0] == unit]
        if not cands:
            # @impl REQ-SB-011 : compiled but not linked (--gc-sections, an overridden weak
            # definition): it can't be on any path, so it is counted, not an error. A function that
            # IS in the image and gets no frame still fails later (REQ-SB-002).
            image.not_linked.append(f"{e.file}:{e.name}")
            continue
        if len(cands) > 1:
            errors.append(f"{e.where}: {e.name} matches {len(cands)} functions in the ELF")
            continue
        cands[0].frame, cands[0].frame_source = e.frame, f"gcc .su ({e.file}:{e.line})"
    for name, (nbytes, source) in project.frames.items():
        fns = image.by_name(name)
        if len(fns) != 1:
            errors.append(f"{project.path.name} frames.{name}: matches {len(fns)} functions in the ELF")
            continue
        if fns[0].frame is not None:
            errors.append(f"{project.path.name} frames.{name}: already has a compiler frame "
                          f"({fns[0].frame} B); remove the annotation")
            continue
        fns[0].frame, fns[0].frame_source = nbytes, f"annotation: {source}"
    if errors:
        raise AnalysisError(errors)


def _candidates(image: Image, title: str) -> list[Function]:
    if ":" in title:                                    # GCC writes statics as "path:name"
        path, _, name = title.rpartition(":")
        base = path_base(path)
        # GCC names a static by the unit it was compiled in; a static inline from a header is
        # declared in the header, so match the compile unit first, then the declaring file.
        return ([f for f in image.by_name(name) if f.unit == base]
                or [f for f in image.by_name(name) if f.decl and f.decl[0] == base])
    return [f for f in image.by_name(title) if f.is_global] or image.by_name(title)


def _resolve_title(image: Image, title: str) -> Function | None:
    cands = _candidates(image, title)
    return cands[0] if len(cands) == 1 else None


def build_graph(image: Image, witness: Witness, project: Project) -> Graph:
    g = Graph()
    errors = []
    for e in witness.edges:
        srcs = _candidates(image, e.source)
        if not srcs:
            # @impl REQ-SB-011 : an edge out of a function the linker removed can't be on any path
            image.not_linked_edges += 1
            continue
        if len(srcs) > 1:
            errors.append(f"call graph: caller '{e.source}' matches {len(srcs)} functions in the ELF")
            continue
        src = srcs[0]
        if e.target == INDIRECT:
            # (part of REQ-SB-101: compiler sites by source location; instruction addresses need the binary witness)
            g.sites.setdefault(src.addr, []).append(e.loc)
            continue
        dst = _resolve_title(image, e.target)
        if dst is None:
            g.unresolved.setdefault(src.addr, []).append(e.target)
        else:
            g.calls.setdefault(src.addr, []).append((dst.addr, "call"))
    for ind in project.indirect:
        fns = image.by_name(ind.function)
        if len(fns) != 1:
            errors.append(f"indirect '{ind.function}': matches {len(fns)} functions in the ELF")
            continue
        targets = []
        for t in ind.targets:
            # (part of REQ-SB-114: the error half; the "missing plausible target" warning comes with tier 4)
            tf = image.by_name(t)
            if len(tf) != 1:
                errors.append(f"indirect '{ind.function}' -> '{t}': matches {len(tf)} functions in the ELF")
            elif tf[0].addr not in image.address_taken:
                errors.append(f"indirect '{ind.function}' -> '{t}': {t} is never address-taken, "
                              "so no pointer can hold it")
            else:
                targets.append(tf[0].addr)
        g.listed[fns[0].addr] = (targets, ind.reason)
    if errors:
        raise AnalysisError(errors)
    return g


def _walk(image: Image, g: Graph, entry: Function) -> tuple[int, list[Step]]:
    """Deepest path from entry. Errors for missing frames, unbound sites and cycles."""
    memo: dict[int, tuple[int, list[Step]]] = {}
    errors: list[str] = []
    seen_err: set[str] = set()

    def err(msg: str) -> None:
        if msg not in seen_err:
            seen_err.add(msg)
            errors.append(msg)

    def visit(fn: Function, via: str, stack: list[tuple[int, str]]) -> tuple[int, list[Step]]:
        addrs = [a for a, _ in stack]
        if fn.addr in addrs:
            # @impl REQ-SB-151 : a cycle is detected (on the resolved graph) and reported with its members
            # @impl REQ-SB-152 : an unannotated cycle is an error listing its edges with their provenance
            members = stack[addrs.index(fn.addr):] + [(fn.addr, via)]
            text = image.functions[members[0][0]].name
            for addr, how in members[1:]:
                text += f" -[{how.split(':')[0]}]-> {image.functions[addr].name}"
            err(f"recursion: {text} (annotate a depth bound or remove it)")
            return 0, []
        if fn.addr in memo:
            d, p = memo[fn.addr]
            return d, [Step(fn, via)] + p[1:]
        if fn.frame is None:
            # @impl REQ-SB-002 : a function on an analysed path with no frame is an error naming it
            err(f"{fn.name}: no frame from any witness (no .su; add a [frames] annotation with its source)")
        for title in g.unresolved.get(fn.addr, []):
            err(f"{fn.name} calls '{title}', which is not a function in the ELF")
        callees = list(g.calls.get(fn.addr, []))
        if fn.addr in g.sites:
            if fn.addr not in g.listed:
                err(f"{fn.name}: indirect call at {', '.join(g.sites[fn.addr])} has no binding "
                    "(add an [[indirect]] entry)")
            else:
                targets, reason = g.listed[fn.addr]
                callees += [(t, f"listed: {reason}") for t in targets]
        best, best_path = 0, []
        stack.append((fn.addr, via))
        for addr, how in callees:
            d, p = visit(image.functions[addr], how, stack)
            if d > best:
                best, best_path = d, p
        stack.pop()
        total = (fn.frame or 0) + best
        memo[fn.addr] = (total, [Step(fn, via)] + best_path)
        return memo[fn.addr]

    depth, path = visit(entry, "", [])
    if errors:
        raise AnalysisError(errors)
    return depth, path


def check_task(image: Image, g: Graph, project: Project, task) -> StackResult:
    fns = image.by_name(task.entry)
    if len(fns) != 1:
        raise AnalysisError(f"task '{task.entry}': matches {len(fns)} functions in the ELF")
    depth, path = _walk(image, g, fns[0])
    if task.stack_symbol:
        try:
            configured = image.object_size(task.stack_symbol)
        except AnalysisError as e:
            raise AnalysisError([f"task '{task.entry}': {m}" for m in e.messages]) from None
        src = f"ELF symbol {task.stack_symbol}"
    else:
        configured, src = task.stack_bytes, "project file"
    prof = project.profile
    switch = prof.switch_fpu if task.fpu else prof.switch_basic
    # @impl REQ-SB-202 : required = deepest path + the profile's switch frame for the task's FPU use
    required = depth + switch
    # @impl REQ-SB-302 : smallest size meeting the rule, rounded up to the profile's alignment
    align = prof.stack_alignment
    recommended = math.ceil(math.ceil(required / project.margin_rule) / align) * align
    used = required / configured if configured else math.inf
    # @impl REQ-SB-301 : a stack fails when required > margin_rule x configured
    status = "FAIL" if required > project.margin_rule * configured else "ok"
    if status == "ok" and project.oversized_above is not None and (1 - used) > project.oversized_above:
        status = "OVERSIZED"
    return StackResult(task.entry, path, depth, switch, required, configured, src, used, recommended, status)


def run(image: Image, witness: Witness, project: Project) -> list[StackResult]:
    attach_frames(image, witness, project)
    g = build_graph(image, witness, project)
    results, errors = [], []
    for t in project.tasks:
        try:
            results.append(check_task(image, g, project, t))
        except AnalysisError as e:
            errors += [f"task {t.entry}: {m}" for m in e.messages]
    if errors:
        raise AnalysisError(errors)
    return results
