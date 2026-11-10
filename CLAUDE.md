# CLAUDE.md — context for Claude Code

`stack_bound` computes a safe upper bound for every stack in an embedded firmware image (each
RTOS task, plus the interrupt stack of each core) from the linked ELF and optional compiler output.
It is the owner's own design and a portfolio piece. traveo-body-domain is its first consumer and
includes it as a submodule at `tools/stack_bound`. Keep this file short and current.

## Read before changing anything

- `docs/idea.md`: what the tool is. `docs/adr/ADR-0001-architecture.md`: the decisions (D1–D15).
- `docs/requirements/stack_bound.md`: `REQ-SB-*`. New code that serves a requirement carries its
  `@impl` tag, and its test carries the `@test` tag (`docs/traceability-convention.md`).

## Rules

1. **No silent drops.** Anything the tool can't see either fails the run, naming the place, or
   becomes a written assumption listed in the report. Never treat an unknown frame as zero, and never
   skip an unknown construct in a parser.
2. **The ELF is the referee, and there are two witnesses.** The binary witness and the compiler witness must
   agree. Don't add a code path that trusts one source alone when both are present.
3. **Profiles hold facts, plugins hold logic.** Platform numbers go in TOML profiles, with their
   source cited. New formats and instruction sets are plugins. The core never mentions a vendor,
   board or project.
4. **No consumer-specific content** in this repository (REQ-SB-404). TRAVEO profiles and
   annotations live in traveo-body-domain.
5. **Every non-trivial design choice gets an ADR** in `docs/adr/`, with alternatives and tradeoffs.
   The owner writes blog posts from that reasoning.
6. **Tests first** where practical: `pytest`, one test module per module. Run `python -m pytest` and
   `python tools/trace_report.py --check` before handing back. Regenerate the matrix with
   `python tools/trace_report.py` when requirements or tags change.

## Conventions

Python 3.11+. Dependencies: `pyelftools`, `capstone`; `tomllib` from the standard library. Exit codes:
0 pass, 1 check failed, 2 analysis error, 3 usage error (ADR-0001 D11).
