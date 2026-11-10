# stack_bound: the idea

**Status:** draft for review · **Date:** 2026-11-10

> `stack_bound` computes a **safe upper bound for every stack** in an embedded firmware image: each
> RTOS task's stack, and the interrupt stack of each core. It works from the build's own output,
> shows the deepest path behind every number, and **refuses to guess**. Where it can't prove
> something, it fails or names the assumption it made.

This page says what the tool is and how it works, at the level of product requirements. The
decisions, alternatives and requirement IDs are in
[ADR-0001](adr/ADR-0001-architecture.md).

---

## 1. The problem

Embedded stacks are sized from a **runtime high-water mark**: run the firmware, look at how much
of the stack was touched, add a bit. A high-water mark only measures the paths that **actually ran**
on the bench. Failure paths (error handling, retries, logging a fault) are the ones that rarely run
and often go deepest.

The first consumer, traveo-body-domain, hit exactly this. A CAN task's stack was sized from a
high-water mark taken before a crypto call existed. The first real `crypto_mac()` overflowed it.
A static walk of the call graph found the worst case (856 B on a 768 B stack) in seconds.

Runtime protections (FreeRTOS overflow checks, stack canaries, MPU guard regions) **detect** an
overflow after it happens. On an ECU, "detect and reset" is still a reset. `stack_bound`
**prevents** it at build time. The two complement each other; neither replaces the other.

## 2. Who uses it, and for what

| Who | When | Question it answers |
|---|---|---|
| Firmware developer | After a build, before flashing | "Will any stack overflow on *any* path, not only the ones I tested?" |
| CI | Every pull request | "Did this change make a stack deeper, and by how much, through which path?" |
| Reviewer | Code review | "Which assumptions does this number depend on, and are they still true?" |
| Integrator / RAM budget owner | Release | "Which stacks are oversized? How much RAM can I reclaim?" |
| Safety / security assessment | Evidence | "Show the worst case per stack, with its path and every assumption written down." |

## 3. What it reports

For **every stack** in the image:

| Field | Meaning |
|---|---|
| **required** | The computed worst case: deepest path + the platform's frames |
| **configured** | What the build actually reserves (read from the ELF, not typed in) |
| **margin** | How much of the configured stack the worst case leaves free |
| **recommended** | The smallest size that meets the margin rule (default: worst case ≤ 80% of the stack; each project can set its own) |
| **status** | `ok`, `FAIL` (margin too small), or `OVERSIZED` (RAM to reclaim) |
| **worst path** | Every function on the deepest path, with its frame, and **how each call was found** |
| **assumptions** | Every annotation, exclusion and profile value the number depends on |

The stacks it knows about:

- **Task stacks:** one per task, found automatically from task-creation calls
  (`xTaskCreateStatic(entry, …, size, buffer, …)`). Worst case = deepest path from the task entry +
  the context-switch frame.
- **RTOS-owned tasks:** the timer task (it runs every timer callback) and the idle task (it runs
  the idle hook). People often guess these sizes.
- **The main stack, one per core:** startup and `main()` before the scheduler starts, then **every
  interrupt**, nesting by priority. Worst case = the larger of the two (on Cortex-M with FreeRTOS),
  or their sum on platforms where interrupts can arrive during `main()`.
- **Platforms where interrupts run on the task's stack:** the interrupt chain is added to every task
  instead. The platform profile says which model applies.

A callback is charged to **the stack it runs on**, not to the code that registered it. An interrupt
callback costs the main stack, and a timer callback costs the timer task.

## 4. How it works

```
 compiler output        linked ELF            profiles + project notes
 (.su frames, .ci       (symbols, DWARF,      (CPU, RTOS, toolchain,
  call graph)            code, const data)     entries, annotations)
        \                    |                    /
         ---------->  neutral model  <-----------
                  functions · edges · unknowns
                             |
              resolve   function pointers, recursion, gaps
                             |
               walk     deepest path from every entry point
                             |
              check     + platform frames, against the configured size and margin
                             |
             report     text · JSON · SARIF · diff against a baseline
```

### Principle 1: the linked ELF is the referee

Every compiler produces an ELF. The tool lists **every function from the ELF's symbol table** and
then attaches what it knows about each one. A function with no information on an analysed path is
**an error, never a zero**. That one rule catches LTO, prebuilt libraries, assembly files and
vendor binaries, whatever the compiler. The tool requires an unstripped ELF built with `-g`
(development builds always have both). It refuses anything else with a clear message.

**DWARF** is the debug information inside the ELF (sections `.debug_*`, produced by `-g`, never
flashed, and it doesn't change the code). The tool uses it for each function's source file and line,
for types and struct layouts, and for call-site argument values when the compiler records them.

### Principle 2: two independent witnesses that must agree

| Witness | What it gives | Availability |
|---|---|---|
| **Binary** (ELF + disassembly) | Each function's stack use, by tracking SP through every instruction; calls; tail calls; indirect branches | Any compiler, given a decoder for the instruction set |
| **Compiler** (GCC `-fstack-usage` + `-fcallgraph-info`, later Arm Compiler, IAR…) | Exact frames and the compiler's own call graph | Toolchains that export it |

When both are present they're **cross-checked**: same function set (stale compiler data fails), same
frames (a mismatch uses the larger and is reported), and the compiler version in the ELF matches the
toolchain profile. So the answer to *"what if I change the compiler options?"* is: change anything.
The two witnesses must still agree, or the run fails.

### Principle 3: no silent drops

Anything the tool can't see either **fails the run**, naming the place, or becomes a **written
assumption** that is listed in the report and checked against the binary where possible. A tool that
quietly drops an indirect call reports 552 B for a task whose real worst case is 1256 B.

### Principle 4: profiles hold facts, plugins hold logic

New platforms are added as **data** wherever possible. Code is only needed for a new file format or
instruction set.

| Extension | Kind | Holds |
|---|---|---|
| CPU profile | data | exception frames, stack alignment, FPU frame |
| RTOS profile | data | context-switch frame, interrupt-stack model, task-creation and callback-registration APIs |
| Toolchain profile | data | which frontend to use, the compiler version, library function frames, noreturn functions |
| Project config | data | margin rule, extra entry points, annotations, policy |
| Frontend | plugin | reads one compiler's output into the neutral model |
| Instruction-set decoder | plugin | the binary witness for one architecture |
| Pointer resolver | plugin | one tier of function-pointer resolution |
| Reporter | plugin | one output format |

Profiles combine in layers: CPU → RTOS → toolchain → project. The report shows which layer set each
value.

## 5. Function pointers: the headline feature

Embedded code is full of them: HAL callbacks, interrupt handlers installed at runtime, RTOS timers,
driver tables, task entries. Most stack tools silently drop them. `stack_bound` handles them in five
steps.

1. **Find every indirect call site**, from both witnesses. The binary finds every `blx rN`, every
   `bx rN` that isn't a return (an indirect tail call), and every write to `pc`. A site the binary
   sees but the compiler doesn't report fails the run. Compiler-generated `switch` tables (`tbb`,
   `tbh`) are recognised as jumps inside a function, not calls.
2. **Narrow the candidates with a funnel:** every function in the ELF → the **address-taken**
   ones (their address appears in data or code) → the **type-compatible** ones (DWARF prototype) →
   the **bound targets**.
3. **Bind targets by following values, not types**, so `void *` casts don't break it:

   | Tier | Source | Typical case |
   |---|---|---|
   | 1. Const data | `.rodata`: struct members, arrays, C++ vtables | driver/port tables, dispatch arrays, virtual calls |
   | 2. Initialised data | `.data` initial values stored in the ELF | generated HAL config structs (`.rxCallback = …`) |
   | 3. Value tracking | registration calls and stores, in the binary + DWARF call-site values | `Cy_SysInt_Init(&cfg, isr)`, `xTimerCreate(…, cb)`, `s_cb = fn`, a config struct filled on the stack |
   | 4. Type match | DWARF prototypes over the address-taken set | leftovers with trustworthy types |
   | 5. Address-taken | the binary | the last resort, for `void *` containers |
   | Listed by hand | an annotation, **checked against tier 5** | what nothing above can express |

   Annotations name **the rule, not the answer**: "targets are whatever is stored in
   `ipc_port_if_t.transact`", or "argument 2 of `Cy_SysInt_Init` is an interrupt handler". The
   binary supplies the facts, so adding a new driver never makes an annotation stale.
4. **Check every human claim:** a listed target that isn't address-taken or type-compatible fails.
   A plausible target that's missing from a list produces a warning. A target whose prototype doesn't
   match the call site is reported as a **type-punned call** (MISRA C:2012 rule 11.1).
5. **Repeat until nothing changes:** new edges can reveal new registration calls, so resolution
   loops until no new targets appear.

A **project policy** sets how far down the tiers a run may go (for example "value tracking at
worst"). Every edge in the report shows the tier that found it.

## 6. Other hard cases it handles

| Case | How |
|---|---|
| **Recursion** | Cycles found after pointer resolution. A cycle needs a depth annotation with a reason, or the run fails. Cost = depth × the most expensive cycle + the most expensive way out. A cycle that exists only because of a type-match edge is reported as such, so you tighten the edge instead. Doubles as a MISRA rule 17.2 check |
| **Tail calls** | The caller's frame is gone, so the depth is the larger of the two frames, not their sum |
| **Assembly and inline asm** | The binary witness tracks SP through every instruction. SP loaded from a register (context switch, startup) fails unless a profile supplies that frame |
| **LTO, prebuilt libraries** | The ELF inventory flags missing compiler data; the binary witness covers it |
| **`-fstack-protector`** | `__stack_chk_fail` runs at the deepest point on the same stack, so it's counted |
| **`std::function`, lambdas** | The stored invoker is a value-tracking store; the rest are ordinary calls |
| **Paths that never run together** | Optional exclusion annotations with reasons, all listed in the report |

## 7. Inputs and outputs

**Inputs:** the linked ELF (unstripped, with DWARF) · optional compiler output (`.su`/`.ci`) ·
profiles · a project file (`stack_bound.toml`).

**Outputs:** a readable report · JSON (a versioned schema, also used as the baseline) · SARIF
(so CI shows findings inline on a pull request) · a diff against a baseline ("`can_task` +160 B
since main, through `crypto_report`") · distinct exit codes for pass, check failure and analysis
error.

## 8. What it is not

- **Not a runtime monitor.** Canaries, RTOS overflow checks and MPU guard regions stay; they're
  the last line of defence.
- **Not a proof of feasibility.** It bounds every path in the call graph, including paths that never
  run together. That over-estimates; it never under-estimates. Commercial analysers based on
  abstract interpretation (e.g. AbsInt StackAnalyzer) go further here.
- **Not for stripped or debug-less builds.** Refused, by design.
- **Not a source-code analyser.** It analyses what the compiler and linker produced, which is what
  runs.

## 9. Limits it states openly

1. **Truly dynamic function addresses** (computed from input, loaded from external memory) can't be
   resolved by any tool. They need an explicit list, still checked against the address-taken set.
2. **Infeasible paths** are excluded only by annotation, never proved.
3. **Platform frames** (exception entry, context switch) come from profiles, so a wrong profile gives
   a wrong number. Profiles are versioned and cite their source (the architecture manual, the RTOS
   port's code).

## 10. How it compares

| Tool | Data | Function pointers | Gap `stack_bound` closes |
|---|---|---|---|
| `avstack.pl`, puncover, similar scripts | `.su` or objdump | Silently dropped | No silent drops; ELF inventory |
| Compiler/linker reports (armlink `--callgraph`, IAR stack usage) | Own toolchain only | Manual control files | Toolchain-neutral; claims checked against the binary |
| AbsInt StackAnalyzer | Binary, abstract interpretation | Strong | Open, scriptable, CI-native; weaker on feasibility |

What makes it different: **two witnesses that must agree, function-pointer tiers that follow values,
every edge labelled with how it was found, and per-stack charging of callbacks.**

## 11. First support row and extension directions

| | First supported | Extension directions |
|---|---|---|
| Compiler witness | GCC (`.su`/`.ci`) | Clang, Arm Compiler 6, IAR, GHS |
| Instruction-set decoder | Arm Thumb-2 (Cortex-M) | RISC-V, AArch64, others |
| Language | C | C++ (vtables, `std::function`); exceptions later |
| RTOS profile | FreeRTOS on Cortex-M4F / M7 | Zephyr, bare-metal, others |

## 12. Where it lives

Its **own repository**, used by projects as a **git submodule** (`tools/stack_bound`), so each
project pins the exact tool version its reports came from. The tool contains no project-specific
content: a project's profiles, annotations and margin rule live in that project.
traveo-body-domain is the first consumer and the first case study.

## Glossary

| Term | Meaning |
|---|---|
| **ELF** | The linked output file: code, data, symbols, and (with `-g`) DWARF |
| **DWARF** | Debug information inside the ELF: source locations, types, struct layouts, call sites |
| **Frame** | The stack one function uses: saved registers + locals |
| **Witness** | An independent source of frames and calls (the binary or the compiler) |
| **Indirect call** | A call through a function pointer; the target isn't in the instruction |
| **Address-taken** | A function whose address appears somewhere in data or code, so it can be a pointer target |
| **Tier** | One level of function-pointer resolution; each edge records which tier found it |
| **PSP / MSP** | Cortex-M's two stack pointers: per-task (process) and main/interrupt |
| **SCC** | Strongly connected component: a group of functions that can call each other in a cycle |
