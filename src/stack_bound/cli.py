"""Command-line entry point. A placeholder until the analysis exists (ADR-0001 is proposed)."""
from __future__ import annotations

import argparse
import sys

from stack_bound import __version__

EXIT_USAGE = 3  # ADR-0001 D11: 0 pass, 1 check failed, 2 analysis error, 3 usage error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stack_bound",
        description="Safe upper bound for every stack in an embedded firmware image.",
    )
    parser.add_argument("--version", action="version", version=f"stack_bound {__version__}")
    parser.add_argument("elf", nargs="?", help="linked ELF (unstripped, with DWARF)")
    args = parser.parse_args(argv)
    if args.elf is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    print("stack_bound: analysis not implemented yet (design stage, see docs/idea.md)",
          file=sys.stderr)
    return EXIT_USAGE
