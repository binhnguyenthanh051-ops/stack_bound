"""Project file and platform profile: TOML data, unknown keys refused (ADR-0001 D4)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from stack_bound.errors import AnalysisError

PROFILES = Path(__file__).resolve().parent / "profiles"
DEFAULT_MARGIN = 0.80


@dataclass
class Task:
    entry: str
    stack_symbol: str = ""
    stack_bytes: int = 0
    fpu: bool = True


@dataclass
class Indirect:
    function: str
    targets: list[str]
    reason: str


@dataclass
class Profile:
    name: str
    version: str
    source: str
    switch_fpu: int
    switch_basic: int
    stack_alignment: int


@dataclass
class Project:
    path: Path
    profile: Profile
    margin_rule: float
    margin_layer: str                        # "project" or "tool default"
    oversized_above: float | None
    tasks: list[Task] = field(default_factory=list)
    indirect: list[Indirect] = field(default_factory=list)
    frames: dict[str, tuple[int, str]] = field(default_factory=dict)    # name -> (bytes, source)


def _check_keys(where: str, table: dict, allowed: set[str], required: set[str] = frozenset()) -> None:
    # @impl REQ-SB-402 : unknown keys in a profile or project file are errors
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise AnalysisError(f"{where}: unknown key(s) {', '.join(unknown)}")
    missing = sorted(required - set(table))
    if missing:
        raise AnalysisError(f"{where}: missing key(s) {', '.join(missing)}")


def load_profile(name: str) -> Profile:
    path = PROFILES / f"{name}.toml"
    if not path.is_file():
        known = ", ".join(sorted(p.stem for p in PROFILES.glob("*.toml")))
        raise AnalysisError(f"unknown profile '{name}' (known: {known})")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    _check_keys(path.name, data, {"name", "version", "source", "frame"}, {"name", "version", "source", "frame"})
    frame = data["frame"]
    _check_keys(f"{path.name} [frame]", frame, {"switch_fpu", "switch_basic", "stack_alignment"},
                {"switch_fpu", "switch_basic", "stack_alignment"})
    return Profile(data["name"], data["version"], data["source"], frame["switch_fpu"],
                   frame["switch_basic"], frame["stack_alignment"])


def load(path: Path) -> Project:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    where = path.name
    _check_keys(where, data, {"profile", "margin_rule", "oversized_above", "task", "indirect", "frames"},
                {"profile", "task"})
    # @impl REQ-SB-301 : margin_rule defaults to 0.80; a project may override it
    margin = float(data.get("margin_rule", DEFAULT_MARGIN))
    if not 0.0 < margin <= 1.0:
        raise AnalysisError(f"{where}: margin_rule must be in (0, 1], got {margin}")
    proj = Project(path=path, profile=load_profile(data["profile"]), margin_rule=margin,
                   margin_layer="project" if "margin_rule" in data else "tool default",
                   oversized_above=data.get("oversized_above"))
    for i, t in enumerate(data["task"]):
        _check_keys(f"{where} task[{i}]", t, {"entry", "stack", "stack_bytes", "fpu"}, {"entry"})
        if ("stack" in t) == ("stack_bytes" in t):
            raise AnalysisError(f"{where} task[{i}] ({t['entry']}): give exactly one of 'stack' or 'stack_bytes'")
        proj.tasks.append(Task(t["entry"], t.get("stack", ""), int(t.get("stack_bytes", 0)), bool(t.get("fpu", True))))
    for i, e in enumerate(data.get("indirect", [])):
        _check_keys(f"{where} indirect[{i}]", e, {"function", "targets", "reason"}, {"function", "targets", "reason"})
        if not e["reason"].strip():
            raise AnalysisError(f"{where} indirect[{i}]: an empty reason is not a reason")
        proj.indirect.append(Indirect(e["function"], list(e["targets"]), e["reason"]))
    for name, spec in data.get("frames", {}).items():
        _check_keys(f"{where} frames.{name}", spec, {"bytes", "source"}, {"bytes", "source"})
        proj.frames[name] = (int(spec["bytes"]), spec["source"])
    return proj
