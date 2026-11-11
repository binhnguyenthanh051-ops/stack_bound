"""Text report: per stack, then each worst path with every frame and how each call was found."""
from __future__ import annotations

from stack_bound import __version__
from stack_bound.analyze import StackResult
from stack_bound.elfread import Image
from stack_bound.project import Project


def text(image: Image, project: Project, results: list[StackResult]) -> str:
    # @impl REQ-SB-304 : per stack: required, configured, margin, recommended, status, worst path
    # @impl REQ-SB-309 : records the ELF SHA-256, tool version and profile name/version
    p = project.profile
    lines = [
        f"stack_bound {__version__} | {image.path.name} (sha256 {image.sha256[:12]}) | {image.compiler}",
        f"profile {p.name} v{p.version} | margin: required <= {project.margin_rule:.0%} of configured "
        f"({project.margin_layer})",
        "",
        f"{'STACK':<18}{'REQUIRED':>10}{'CONFIGURED':>12}{'USED':>7}{'RECOMMENDED':>18}  STATUS",
    ]
    for r in results:
        rec = f"{r.recommended} B ({r.recommended // 4} w)"
        lines.append(f"{('task ' + r.entry):<18}{r.required:>8} B{r.configured:>10} B{r.used:>7.0%}"
                     f"{rec:>18}  {r.status}")
    for r in results:
        lines += ["", f"worst path, task {r.entry} ({r.path_bytes} B + {r.switch_bytes} B switch frame, "
                      f"stack from {r.configured_from}):"]
        for i, s in enumerate(r.path):
            arrow = "   " if i == 0 else (" ~> " if s.via.startswith("listed") else " -> ")
            note = f"   [{s.via}]" if s.via.startswith("listed") else ""
            lines.append(f"  {arrow}{s.fn.name} {s.fn.frame} B{note}")
    # @impl REQ-SB-305 : every assumption the result depends on is listed
    assumptions = [f"indirect {i.function} -> {', '.join(i.targets)}: {i.reason}" for i in project.indirect]
    assumptions += [f"frame {n} = {b} B: {src}" for n, (b, src) in project.frames.items()]
    assumptions.append(f"switch frame {p.switch_fpu} B (FPU) / {p.switch_basic} B [profile {p.name}]: {p.source}")
    assumptions.append(f"stack alignment {p.stack_alignment} B [profile {p.name}]")
    assumptions.append(f"margin rule {project.margin_rule:.2f} [{project.margin_layer}]")
    lines += ["", "  ->  direct call    ~>  function-pointer target (from the [[indirect]] list)", "",
              "assumptions:"] + [f"  - {a}" for a in assumptions]
    return "\n".join(lines) + "\n"
