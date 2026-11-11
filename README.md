# stack_bound

A **safe upper bound for every stack** in an embedded firmware image: each RTOS task's stack and
the interrupt stack of each core. It works from the build's own output, shows the deepest path
behind every number, and refuses to guess.

> **Status: 0.2.0, slice 1 + reports.** Architecture accepted in [ADR-0001](docs/adr/ADR-0001-architecture.md).
> Works today: the ELF inventory and DWARF join, the GCC compiler witness (`.su`/`.ci`), function
> pointers bound by a checked list, recursion refused, task stacks checked against the margin, and a
> report as text, JSON and HTML. Next: the binary witness (Thumb-2), value tracking, the interrupt stack, SARIF.

## Run

```bash
python -m stack_bound build/app.elf --su build/ --project stack_bound.toml
```

Add `--json report.json` and `--html report.html` to also write the report as JSON (schema
`stack_bound.report/1`) and as one self-contained page: a bar per stack against its margin, each worst
path as a waterfall, and every assumption. Text, JSON and HTML render the same model.

```text
STACK               REQUIRED  CONFIGURED   USED       RECOMMENDED  STATUS
task task_a            768 B      1024 B    75%     960 B (240 w)  ok
task task_b            760 B       256 B   297%     952 B (238 w)  FAIL

worst path, task task_a (560 B + 208 B switch frame, stack from ELF symbol s_stack_a):
     task_a 16 B
   -> verify 24 B
   ~> crypto_mac 520 B   [listed: g_oracle.mac = crypto_mac (crypto.c)]
```

Exit codes: `0` every stack passes, `1` a stack fails its margin, `2` the analysis can't give a safe
bound (and says why), `3` usage error. The test corpus in `tests/corpus/` is a working example of the
project file.

## Read first

| Document | What it is |
|---|---|
| [docs/idea.md](docs/idea.md) | What the tool does and how it works: the product idea |
| [docs/how-it-reads-thumb2.md](docs/how-it-reads-thumb2.md) | Real Thumb-2 examples: frames, function pointers, tasks |
| [docs/adr/ADR-0001-architecture.md](docs/adr/ADR-0001-architecture.md) | The decisions, their alternatives, and a GCC 14 spike |
| [docs/style-guide.md](docs/style-guide.md) | How every page is written: figure-led Markdown |
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

## License

[MIT](LICENSE): free for anyone to use, modify and redistribute, including commercially. Keep the
copyright notice.
