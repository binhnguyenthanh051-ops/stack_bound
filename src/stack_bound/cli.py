"""Command line: stack_bound ELF --su DIR --project FILE."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stack_bound import __version__, analyze, elfread, gcc, project, report
from stack_bound.errors import AnalysisError

# @impl REQ-SB-308 : 0 pass, 1 check failed, 2 analysis error, 3 usage error
EXIT_PASS, EXIT_FAIL, EXIT_ANALYSIS, EXIT_USAGE = 0, 1, 2, 3


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):          # argparse would exit 2, which means "analysis error" here
        self.print_usage(sys.stderr)
        print(f"stack_bound: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="stack_bound",
                     description="Safe upper bound for every stack in an embedded firmware image.")
    parser.add_argument("--version", action="version", version=f"stack_bound {__version__}")
    parser.add_argument("elf", type=Path, help="linked ELF (unstripped, with DWARF)")
    parser.add_argument("--su", type=Path, required=True, metavar="DIR",
                        help="directory with the build's .su and .ci files (GCC -fstack-usage -fcallgraph-info=su)")
    parser.add_argument("--project", type=Path, required=True, metavar="FILE", help="stack_bound.toml")
    parser.add_argument("--json", type=Path, metavar="FILE", help="also write the report as JSON (schema "
                        f"{report.SCHEMA})")
    parser.add_argument("--html", type=Path, metavar="FILE", help="also write the report as one self-contained HTML page")
    args = parser.parse_args(argv)
    for p, kind in ((args.elf, "ELF"), (args.su, "--su directory"), (args.project, "project file")):
        if not p.exists():
            print(f"stack_bound: {kind} not found: {p}", file=sys.stderr)
            return EXIT_USAGE
    try:
        proj = project.load(args.project)
        image = elfread.load(args.elf)
        witness = gcc.load_dir(args.su)
        results = analyze.run(image, witness, proj)
    except AnalysisError as e:
        print("stack_bound: analysis error, no result:", file=sys.stderr)
        for m in e.messages:
            print(f"  - {m}", file=sys.stderr)
        return EXIT_ANALYSIS
    m = report.model(image, proj, results)
    sys.stdout.write(report.text(m))
    for path, render in ((args.json, report.json), (args.html, report.html)):
        if path is not None:
            path.write_text(render(m), encoding="utf-8")
    return EXIT_FAIL if any(r.status == "FAIL" for r in results) else EXIT_PASS
