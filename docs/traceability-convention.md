# Traceability convention

Every requirement traces **up** to the decision that explains it and **down** to the code that
implements it and the tests that prove it. A script checks the links, so a gap is found by CI, not
by memory.

## IDs

| Artifact | ID format | Where defined |
|---|---|---|
| Decision | `ADR-NNNN` + sub-decision `Dn` | `docs/adr/ADR-NNNN-*.md` (status line `**Status:** proposed/accepted/superseded`, decisions as `### Dn. …`) |
| Requirement | `REQ-SB-NNN` | a row in a table in `docs/requirements/*.md`: `\| REQ-SB-NNN \| text \| ADR-NNNN Dn, … \| planned test \|` |

IDs are stable and never reused. A superseded ADR stays on disk with status `superseded`. The
requirement ID format `REQ-<AREA>-NNN` matches the one used by the first consumer, so tools
recognise both; `SB` is this repository's area.

## Tags in code and tests

One comment per line, with a fixed keyword:

```python
# @impl REQ-SB-104 : address-taken set from data words and literal pools
# @test REQ-SB-104 : Thumb bit is cleared before the address lookup
```

- `@impl <ID>` marks code that implements a requirement or decision; `@test <ID>` marks a test that
  verifies one.
- `<ID>` is `REQ-[A-Z]+-NNN`, `ADR-NNNN`, or `ADR-NNNN Dn`.
- The text after `:` is a hint for people. It isn't parsed.
- Tags are read from `src/`, `tests/` and `tools/`, in Python, C/C++ and assembly files (C and
  assembly are for the validation corpus). `docs/` is never scanned, so examples there are safe.

## What `tools/trace_report.py` checks

It writes `docs/traceability.md` (generated, committed) and fails on any gap:

| Gap | Meaning |
|---|---|
| `duplicate-req` | the same requirement ID defined twice |
| `no-trace` | a requirement with no `ADR-NNNN Dn` reference |
| `bad-trace` | a requirement pointing to an ADR or decision that doesn't exist |
| `dangling` | a tag naming an ID that doesn't exist |
| `uncovered` | a requirement in a **gated** area, with an accepted ADR, that lacks an `@impl` or a `@test` |

**Table 1.** Requirement states.

| State | Meaning | Gap? |
|---|---|---|
| covered | has an `@impl` and a `@test` | no |
| open | its ADR is accepted, but it isn't built and tested yet | only inside a gated area |
| pending | its ADRs are all still proposed | no |

Accepting an ADR means the design is decided, not that it's built. Coverage is enforced **per area**
through `gates` in `pyproject.toml` (`[tool.trace_report]`): add an area's prefix, e.g. `REQ-SB-1`
for function pointers, once that area is implemented. From then on every requirement in it must stay
covered.

`python tools/trace_report.py --check` writes nothing and also fails if the committed matrix is stale.
CI runs it on every push.
