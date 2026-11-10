# stack_bound

A **safe upper bound for every stack** in an embedded firmware image: each RTOS task's stack and
the interrupt stack of each core. It works from the build's own output, shows the deepest path
behind every number, and refuses to guess.

> **Status: design.** The architecture is proposed in
> [ADR-0001](docs/adr/ADR-0001-architecture.md). No analysis is implemented yet.

## Read first

| Document | What it is |
|---|---|
| [docs/idea.md](docs/idea.md) | What the tool does and how it works: the product idea |
| [docs/adr/ADR-0001-architecture.md](docs/adr/ADR-0001-architecture.md) | The decisions, their alternatives, and a GCC 14 spike |
| [docs/requirements/stack_bound.md](docs/requirements/stack_bound.md) | Normative requirements `REQ-SB-*` |
| [docs/traceability.md](docs/traceability.md) | Generated matrix: requirement → decision → code → tests |
| [docs/traceability-convention.md](docs/traceability-convention.md) | How the IDs and tags work |

## Layout

```
src/stack_bound/     the tool (a package; `python -m stack_bound` once installed, or with src/ on PYTHONPATH)
tests/               pytest
tools/trace_report.py  this repository's traceability check
docs/                idea, ADRs, requirements, generated matrix
```

## Develop

Python 3.11+.

```bash
python -m pip install -e ".[dev]"
```

```bash
python -m pytest
```

```bash
python tools/trace_report.py --check
```

## Use in a firmware project

Add it as a git submodule, which pins the exact version a report came from:

```bash
git submodule add <repository URL> tools/stack_bound
```

Keep your project file, profiles and annotations in your own repository. This repository contains
no project-specific content.
