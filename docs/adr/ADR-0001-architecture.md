# ADR-0001: stack_bound architecture

**Status:** proposed · **Date:** 2026-11-10 · **Idea:** [../idea.md](../idea.md)

> How `stack_bound` computes a safe upper bound for every stack in an embedded image, from the
> build's own output. This ADR fixes the architecture: the ELF as referee, two cross-checked
> witnesses, the neutral model, profiles and plugins, function-pointer resolution, recursion, the
> stack model, the check, the report, and how the tool is built, validated and distributed. It
> introduces the requirements `REQ-SB-001…504` ([docs/requirements/stack_bound.md](../requirements/stack_bound.md))
> that code and tests trace to.

## Context

- **Runtime high-water marks only see paths that ran.** Failure paths go deepest and run least.
  traveo-body-domain's W40 overflow (a CAN task's stack sized before a crypto call existed) is the
  motivating case. A 30-line prototype found it statically in seconds.
- **Existing open tools silently drop what they can't see**, function pointers above all. In the
  first consumer's spike, GCC's call graph alone reported **552 B** for a task whose real worst path
  was **1256 B**, because the deepest frame sat behind a function pointer.
- **The tool must not be tied to one compiler, CPU or RTOS**, but the first support row is GCC +
  Cortex-M (Thumb-2) + FreeRTOS. Extending must mean adding data or a plugin, never editing the core.
- **Development builds always carry symbols and DWARF.** Supporting stripped builds adds code and
  ways to be quietly wrong, for no real user.
- **Function pointers are the norm in embedded code**: HAL callbacks, interrupt handlers installed at
  runtime, RTOS timers, driver tables, task entries. Handling them well is the tool's main reason
  to exist.

## Decisions

### D1. The linked ELF is the inventory and the referee

The tool reads the linked ELF directly (symbol table, sections, DWARF), with no external `objdump`.
Every `STT_FUNC` symbol is a function in the inventory. A function on an analysed path with no frame
from any witness is an error, never zero. The ELF must be unstripped and carry DWARF; otherwise the
tool refuses with a clear error.

*Alternatives:* compiler output as the inventory (misses LTO, assembly, prebuilt libraries, with no way
to notice); a degraded mode without DWARF (rejected: no real user, more code, more silent-error paths).

### D2. Two witnesses, cross-checked

- **Binary witness:** per function, track SP through **every** instruction (`push`/`pop`,
  `sub`/`add sp`, `vpush`, pre-indexed stores to SP) and record the maximum depth. Calls (`bl`), tail
  calls (`b`/`bx` to a function), indirect branches. An SP loaded from a register is untrackable: it
  fails unless a profile supplies that function's frame (context-switch and startup code).
- **Compiler witness:** frontend plugins (first: GCC `.su` + `.ci`). Optional.
- **Cross-check when both are present:** the same function set (a mismatch means stale data → error);
  the same frame per function (a mismatch → use the larger, report it; a policy can make it an error);
  the compiler version from the ELF's `.comment` matches the toolchain profile, and selects the
  parser dialect.
- A tail call contributes `max(caller, callee)`, not a sum.

*Alternatives:* compiler data only, with disassembly as a fallback (one witness can be stale without
anyone noticing); binary only (works everywhere, but loses the compiler's exact view and its record
of indirect calls, so it isn't a second witness).

### D3. One neutral model, functions keyed by address

The model holds `functions` (key = ELF address with the Thumb bit cleared; size; file and line from DWARF;
frame per witness), `edges` (kind: call, tail call, indirect, plus **provenance**: witness and tier),
`sites` (indirect call sites, keyed by function + instruction address), `stacks` and `unknowns`.
Compiler data is joined to ELF functions on **(file, line, column, name)** via DWARF, so `static` functions
with the same name and GCC clones (`.constprop.N`, `.isra.N`, `.part.N`) map exactly. Names are
demangled for display only. The model is a versioned JSON schema, so any toolchain can feed it, even
from a script outside the tool.

*Alternative:* key by name (breaks on same-name statics, inline/template copies kept once by the
linker, C++ mangling, clones).

### D4. Profiles hold facts, plugins hold logic

- **Profiles (TOML, layered CPU → RTOS → toolchain → project):** numbers and names only.
  Conditionals become named variants (for example `frame.switch.fpu` / `frame.switch.basic`, chosen per
  task by a flag). The report shows which layer set each value. Unknown keys are errors.
- **Plugins (Python entry points):** frontends, instruction-set decoders, pointer resolvers,
  reporters. Built-ins register through the same mechanism as third-party plugins.

*Alternatives:* a Python config file (it can't be reviewed as data, and a profile becomes code to
trust); hard-coded platform tables (every new platform edits the core).

### D5. Every indirect call site is found by both witnesses

A site is `(function, instruction address)`. The binary finds `blx rN`, `bx rN` that isn't a return
(an indirect tail call), and writes to `pc` (`ldr pc, …`, `mov pc, …`). Compiler `switch` tables
(`tbb`, `tbh`, a `ldr pc, [pc, rX, lsl #2]` table bounded by a `cmp`) are jumps inside one function, not
calls. A site found by the binary but not reported by the compiler witness is an error.

### D6. Function-pointer targets come from tiers that follow values; types only filter

| Tier | Source |
|---|---|
| 1. Const data | `.rodata`: struct-member bindings over **every instance of a DWARF type**, arrays, C++ vtables |
| 2. Initialised data | the initial values of `.data`, as stored in the ELF |
| 3. Value tracking | registration and store sites (D7) |
| 4. Type match | DWARF prototype over the address-taken set |
| 5. Address-taken | words in data, literal-pool loads, `movw/movt`, `adr` (Thumb bit honoured) |
| Listed | an annotation, checked against tier 5 and the type |

- Annotations name **a rule** (`binding = "ipc_port_if_t.transact"`), not a target list, wherever
  possible.
- **Type is a filter, never a requirement:** it never removes a target found by tiers 1–3. A
  value-found target whose prototype differs from the site's pointer type is reported as a
  **type-punned call**.
- **Listed targets are checked:** not address-taken, or type-incompatible → error. An
  address-taken, compatible function missing from a list → warning.
- **Policy `max_fallback`** (project) sets the lowest tier a site may use. Needing a lower tier is an
  error. Every edge carries its tier into every output.

*Alternatives:* type-based resolution first (breaks on `void *` and casts, which are common in
embedded code); manual lists only (go stale silently); points-to analysis (heavy, and still unsound
on binaries).

### D7. Value tracking: registration and store sites, repeated until nothing changes

- **A registration rule** names an API, an argument, an optional struct member, and `runs_on`:
  ```toml
  [[register]]
  api = "Cy_SysInt_Init"
  param = 2
  runs_on = "isr"
  ```
- **Binary witness:** at every call to the API (direct, or indirect once it's resolved), find the
  argument register's value by constant propagation inside the calling function: `ldr =`, `adr`,
  `movw/movt`, constant `add`/`sub`. A value passed straight through from the caller's own argument is
  followed into *its* callers, up to a configured depth.
- **A struct member as the argument:** DWARF gives the member offset. The tool finds the store to
  that offset in a stack slot (the address formed by `add rN, sp, #k`), a global (tier 2 + stores), or
  const data (tier 1).
- **Store sites:** `binding = "var:s_cb"` (or `"var:g_cfg.cb"`) tracks the values stored there.
- **DWARF call-site parameter values** (when the compiler records them) are a second witness for
  constant arguments; if they disagree with the binary, that's an error.
- **Repeat until stable:** newly resolved edges can expose new registration calls, so resolution
  loops until an iteration adds nothing. It terminates because each iteration only adds targets from
  a finite set.
- **`runs_on`** (`self`, a named task such as the RTOS timer task, or `isr`) decides **which stack**
  the callee is charged to (D9).
- The RTOS and HAL profiles ship the standard rules (task creation, timers, deferred calls, interrupt
  registration), so most projects write none.

### D8. Recursion: strongly connected components, depth by annotation

After resolution, Tarjan's algorithm finds the strongly connected components (SCCs). A cycle with no
annotation is an error that lists its edges **with their provenance**, so a cycle created only by a
tier-4/5 edge is visible as such. An annotated cycle (`max_depth`, `reason`) costs
`max_depth × (the most expensive simple cycle, by Johnson's algorithm) + (the most expensive exit)`.
Above a configured SCC size, the cost is `max_depth × (sum of the SCC's frames)` and is labelled as an
over-estimate.

### D9. The stack model: task stacks and one main stack per core

- **Task stacks:** discovered from the RTOS profile's task-creation APIs through value tracking
  (entry, stack size, buffer symbol). The project may add or override them.
  `required = deepest path from the entry + the switch frame` (the FPU or basic variant, per task).
- **RTOS-owned tasks:** the timer task (its loop + the deepest timer callback) and the idle task (+ the
  idle hook).
- **The main stack, per image:** entry points are the reset path and the vector table (read from the
  ELF), plus handlers registered with `runs_on = "isr"`. The configured size comes from linker
  symbols named by the toolchain profile.
  - **Interrupt chain** = Σ over priority levels of the deepest handler at that level + one exception
    frame per nesting level. Priorities come from value tracking or the project; a handler with an
    unknown priority is put at its own level (safe).
  - The RTOS profile's interrupt model decides the combination: **separate** + interrupts masked until
    the scheduler starts → `max(pre-scheduler path, interrupt chain)`; interrupts possible before the
    scheduler → the **sum**; **shared** (interrupts run on the task's stack) → the chain is added to
    every task.
- **One run per image:** a multi-core part is analysed one image at a time.

### D10. The check: a margin rule, a recommended size, oversized stacks

`required ≤ margin_rule × configured`. The tool's **default is `margin_rule = 0.80`** (a 20%
margin). The real margin is project-specific, so a project sets its own in its project file, and the
report shows which layer set it. `recommended` = the smallest size that meets the rule, rounded
up to the profile's stack alignment, also shown in words. A margin above the project's
`oversized_above` threshold is `OVERSIZED` (a warning, not a failure).

### D11. The report

Per stack: required, configured, margin, recommended, status, and the worst path with each frame and
each edge's provenance. A list of every assumption the result depends on: annotations, exclusions,
and profile values with their layer. Formats: text, JSON (versioned schema, usable as a baseline),
SARIF. **Diff** against a baseline JSON: the per-stack change and the changed path. Inputs recorded
for reproducibility: the ELF's SHA-256, the tool version, and each profile's name and version.
Exit codes: `0` pass, `1` check failed, `2` analysis error (unresolved or unknown), `3` usage error.

### D12. Exclusions for paths that can't run together

An optional annotation lists path pairs that can't occur together, each with a reason. The walk
never combines an excluded pair. Every exclusion is listed in the report as an assumption. The tool
does not try to prove exclusions.

### D13. Implementation

Python 3.11+. ELF and DWARF via `pyelftools`. Instruction decoding via `capstone` (structured
instructions, many architectures, no text parsing). TOML via the standard library's `tomllib`.
Tests with `pytest`. Compiler-output parsers are **real parsers** (a tokenizer and grammar for `.ci`'s
graph format), strict (unknown constructs are errors), and selected by compiler version, with a
fixture set per supported version.

*Alternative:* parse `objdump -d` text (the format varies between binutils versions and vendors, and
it needs the matching `*-objdump` for each architecture).

### D14. Validation: a corpus with golden results and measured stacks

Small C and C++ programs, one per behaviour, each with its expected frames, edges and pointer
targets: const struct, dispatch array, callback argument, returned pointer, runtime registration,
`void *` cast, indirect tail call, pointer to a `static` function, a struct filled on the stack and
then registered, recursion, a `switch` table, inline asm, virtual methods, `std::function`. Built at
`-O0`, `-O2`, `-Os` with every supported compiler. Each runs under QEMU with a painted stack, and
**`static ≥ measured`** must hold for every entry point.

### D15. Its own repository, used as a submodule

The tool has its own repository, CI, corpus and release tags. Consumers add it as a git submodule
(e.g. `tools/stack_bound`), which pins the exact version, and keep their profiles, annotations and
margin rule in their own repository. The tool contains no consumer-specific content. It runs as
`python -m stack_bound`, either installed as a package (`pip install -e tools/stack_bound`) or from
a checkout with its `src/` on `PYTHONPATH`.

*Alternatives:* `pip install` from a git tag (clean, but not "in `tools/`" and awkward to edit while
testing); a plain clone (no pinned version, so results can't be reproduced).

## Requirements

This ADR introduces the requirements `REQ-SB-001…504`, kept in
[docs/requirements/stack_bound.md](../requirements/stack_bound.md). Each one traces to a decision
above (`ADR-0001 Dn`) and to the tests that prove it. "shall" is normative; IDs are never reused.

## Consequences

- **(+)** A stack number comes with its path and its assumptions, and no part of it is silently dropped.
- **(+)** Function pointers, the usual blind spot, become the strongest part: bindings follow values,
  so annotations don't go stale, and claims are checked against the binary.
- **(+)** Independent of the compiler (binary witness) while precise where the compiler helps (compiler
  witness). The two must agree, so changing compiler options is safe.
- **(+)** Extending is data first (profiles) and plugins second; the core doesn't change.
- **(−)** A larger build than a script: an ELF/DWARF reader, a decoder, value tracking, a corpus with
  QEMU. Value tracking is the most complex part and needs the corpus to stay correct.
- **(−)** Profiles must be right. A wrong exception or switch frame gives a wrong bound, so each
  profile cites its source.
- **(−)** It's an upper bound over call-graph paths. Without exclusions it over-estimates paths that
  can't run together.
- **(−)** Strict by design: new indirect sites, cycles and unknown functions fail until they're
  handled. That's the intended cost.

## Alternatives considered (as the overall approach)

| Option | Why not |
|---|---|
| A GCC-only script (`.su` + `.ci`) | Tied to one compiler; drops indirect calls; can't see assembly or LTO gaps |
| Disassembly only | Loses the compiler's exact view and its record of indirect calls; no second witness |
| Extend `avstack.pl` / puncover | Same data, but silent drops are built into their design |
| Commercial analyser (AbsInt StackAnalyzer) | Stronger on feasibility, but licensed and closed; not a portfolio piece; named in the docs as the industrial answer |
| Runtime measurement only | Sees only paths that ran; kept as the cross-check (D14) and as the consumer's last line of defence |

## Open items

- **Submodule:** this repository was created locally inside traveo-body-domain's `tools/stack_bound`.
  It still needs a remote (GitHub), and then registering as a real submodule in the consumer.
- **Confirm across optimisation levels and GCC versions:** the GCC 14 findings below come from an
  `-Og` build. Repeat at `-O2`/`-Os` in the corpus (D14), and check how many call-site values survive
  there.

## Spike: GCC 14.2.1 output (2026-11-10)

Taken from traveo-body-domain Node B (`proj_cm7`, Cortex-M7). Six files (`can_task.c`, `main.c`,
`port_crypto.c`, `secoc.c`, `secoc_rx.c`, `log.c`) were recompiled with the project's own flags from
`compile_commands.json` (`-g -Og`, DWARF 5) plus `-fstack-usage -fcallgraph-info=su`. Output went to
a scratch folder, and the project's build was untouched.

| Question | Result | Consequence |
|---|---|---|
| Do `.ci` edges carry the call-site location? | **Yes.** Every edge, including each `__indirect_call`, has `label: "file:line:col"` (e.g. `secoc_rx.c:90:55`) | The compiler witness identifies indirect sites **per call**, not per function. D5 joins them to the binary's sites through the DWARF line table (address → line:col) |
| How are `static` functions named in `.ci`? | `title: "<file>:<name>"` (e.g. `secoc_rx.c:drop_mac`); external functions by bare name | GCC already separates same-name statics. External callees appear with their *declaration* location (a header), so they're joined by linker name, which is unique |
| Do `.su` locations match DWARF? | **Yes, exactly:** `secoc_rx.c:68:20:secoc_rx_process` ↔ `DW_AT_decl_file/line/column` = 68/20 | The join key gains the column: (file, line, column, name) |
| Does DWARF record call-site argument values? | **Yes, at `-Og`:** 57 `DW_TAG_call_site_parameter` entries in `can_task.c`, 40 in `secoc_rx.c` | REQ-SB-110 has real data to work with |
| Can tasks be found from DWARF alone? | **Yes.** At the `xTaskCreateStatic` call: `r0` = `DW_OP_addr` of the task entry (addend 1 = the **Thumb bit**), `r2` = `384` (the stack depth in words), and the stack-passed arguments (`DW_OP_breg13` +4/+8) = the buffer and TCB addresses | REQ-SB-201 needs no source parsing and no project list: entry, depth and buffer come straight from the build |
- **The first consumer's ADR-0025** becomes the *project's* decisions: its profiles and annotations,
  its margin rule, its build-script check, and the `LOG_EVT_TASK_STACK` cross-check. It no longer
  holds the method.
- **Traceability namespaces:** the tool's `ADR-0001` and `REQ-SB-*` live in the tool's own
  repository, with its own trace report. The consumer's `trace_report.py` (checked 2026-11-10) only
  reads ADRs and requirements from its own `docs/` folders. It finds tags through `git ls-files`,
  which doesn't descend into a submodule. A nested repository not yet registered as a submodule
  doesn't get scanned either, so there's no collision at any stage.
- **Decide** the JSON model schema and the report schema (versioned) before the first plugin is
  written.
