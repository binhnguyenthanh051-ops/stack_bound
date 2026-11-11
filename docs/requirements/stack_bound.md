# stack_bound requirements: `REQ-SB-001…504`

Normative requirements for `stack_bound`. "shall" is normative. IDs are stable and never reused.
Each requirement traces **up** to an ADR decision (the *why*) and **down** to the `@impl`/`@test`
tags that prove it ([traceability convention](../traceability-convention.md)). The generated
matrix is [docs/traceability.md](../traceability.md).

Hundreds group the areas: `0xx` inputs and witnesses, `1xx` function pointers, `15x` recursion,
`2xx` stacks, `3xx` check and report, `4xx` configuration and extension, `5xx` quality.

56 requirements.

## Coverage matrix

| ID | Requirement | Traces | Verified by (planned) |
|---|---|---|---|
| REQ-SB-001 | The tool shall read the linked ELF directly and shall refuse an ELF with no symbol table or no DWARF, with a message naming what is missing | ADR-0001 D1 | `test_elf_input` |
| REQ-SB-002 | Every `STT_FUNC` symbol shall be in the inventory; a function on an analysed path with no frame from any witness shall be an analysis error naming it | ADR-0001 D1 | `test_inventory` |
| REQ-SB-003 | Functions shall be keyed by address; compiler data shall be joined on DWARF (file, line, column, name), including same-name statics and compiler clones | ADR-0001 D3 | `test_identity`, corpus |
| REQ-SB-004 | The binary witness shall compute each function's frame as the maximum SP depth over all its instructions | ADR-0001 D2 | `test_sp_tracking`, corpus |
| REQ-SB-005 | An SP load from a register shall be an analysis error unless a profile supplies that function's frame | ADR-0001 D2 | `test_sp_tracking` |
| REQ-SB-006 | When both witnesses are present, a difference in function sets shall be an analysis error (stale data) | ADR-0001 D2 | `test_witness_xcheck` |
| REQ-SB-007 | When witnesses disagree on a frame, the larger shall be used and the difference reported; a policy shall be able to make it an error | ADR-0001 D2 | `test_witness_xcheck` |
| REQ-SB-008 | The compiler version in the ELF's `.comment` shall match the toolchain profile and shall select the parser dialect | ADR-0001 D2, ADR-0001 D13 | `test_toolchain_detect` |
| REQ-SB-009 | A tail call shall contribute the larger of the caller's and callee's depth, not their sum | ADR-0001 D2 | `test_tail_call`, corpus |
| REQ-SB-010 | Calls to noreturn functions (e.g. `__stack_chk_fail`) shall be counted with their frame | ADR-0001 D2 | `test_noreturn`, corpus |
| REQ-SB-011 | Compiler-witness entries (frames and call-graph edges) for a function that is not in the linked image (removed by the linker) shall be ignored and counted in the report; an entry that matches more than one function shall be an analysis error | ADR-0001 D3 (addendum 2026-11-11) | `test_slice1` |
| **Function pointers** ||||
| REQ-SB-101 | Every indirect call site shall be identified by (function, instruction address), including indirect tail calls and writes to `pc` | ADR-0001 D5 | `test_sites`, corpus |
| REQ-SB-102 | A site found by the binary witness and not reported by the compiler witness shall be an analysis error | ADR-0001 D5 | `test_sites` |
| REQ-SB-103 | Compiler `switch` jump tables shall be recognised as branches inside one function, not calls | ADR-0001 D5 | `test_switch_tables`, corpus |
| REQ-SB-104 | The address-taken set shall include every function whose address appears in data or is formed in code, with the Thumb bit honoured | ADR-0001 D6 | `test_address_taken` |
| REQ-SB-105 | Tier 1 shall resolve struct-member bindings over every const instance of the named DWARF type, arrays of pointers, and C++ vtables | ADR-0001 D6 | `test_tier_const`, corpus |
| REQ-SB-106 | Tier 2 shall resolve bindings from the initial values of `.data` | ADR-0001 D6 | `test_tier_data`, corpus |
| REQ-SB-107 | Tier 3 shall resolve the value of a registration argument at every call to the API, by constant propagation inside the caller (incl. constant `add`/`sub`) and through pass-through arguments up to a configured depth | ADR-0001 D7 | `test_value_tracking`, corpus |
| REQ-SB-108 | Tier 3 shall resolve a registration through a struct member whether the struct is on the stack, global, or const | ADR-0001 D7 | `test_value_tracking`, corpus |
| REQ-SB-109 | Tier 3 shall resolve the values stored to a named variable or member | ADR-0001 D7 | `test_value_tracking` |
| REQ-SB-110 | Where DWARF records call-site parameter values, they shall be compared with tier 3's result; a disagreement shall be an analysis error | ADR-0001 D7 | `test_callsite_dwarf` |
| REQ-SB-111 | Resolution shall repeat until an iteration adds no target | ADR-0001 D7 | `test_fixpoint` |
| REQ-SB-112 | Type matching shall never remove a target found by tiers 1–3 | ADR-0001 D6 | `test_type_filter` |
| REQ-SB-113 | A resolved target whose prototype differs from the site's pointer type shall be reported as a type-punned call | ADR-0001 D6 | `test_type_filter`, corpus |
| REQ-SB-114 | A listed target that isn't address-taken or isn't type-compatible shall be an analysis error; a compatible address-taken function missing from a list shall be a warning | ADR-0001 D6 | `test_listed_targets` |
| REQ-SB-115 | A site that needs a tier below the project's `max_fallback` shall be an analysis error naming the site | ADR-0001 D6 | `test_policy` |
| REQ-SB-116 | Every edge shall carry its witness and tier in every output format | ADR-0001 D6, ADR-0001 D11 | `test_report_provenance` |
| REQ-SB-117 | A registration rule's `runs_on` shall decide the stack the callee is charged to | ADR-0001 D7, ADR-0001 D9 | `test_runs_on`, corpus |
| **Recursion** ||||
| REQ-SB-151 | Cycles shall be detected as SCCs after pointer resolution | ADR-0001 D8 | `test_recursion` |
| REQ-SB-152 | A cycle with no depth annotation shall be an analysis error listing its edges with their provenance | ADR-0001 D8 | `test_recursion` |
| REQ-SB-153 | An annotated cycle shall cost `max_depth × (the most expensive simple cycle) + (the most expensive exit)`; above the SCC size cap, `max_depth × (sum of frames)`, labelled as an over-estimate | ADR-0001 D8 | `test_recursion` |
| **Stacks** ||||
| REQ-SB-201 | Tasks shall be discovered from the RTOS profile's task-creation APIs, with entry, stack size and buffer resolved from the binary; the project may add or override | ADR-0001 D9 | `test_task_discovery`, corpus |
| REQ-SB-202 | A task's required size shall be its deepest path plus the profile's switch frame for that task's FPU use | ADR-0001 D9 | `test_stack_model` |
| REQ-SB-203 | RTOS-owned tasks shall be analysed, including timer callbacks on the timer task and the idle hook on the idle task | ADR-0001 D9 | `test_stack_model`, corpus |
| REQ-SB-204 | The main stack shall be analysed per image from the reset path, the vector table and `isr` registrations, against the size from the profile's linker symbols | ADR-0001 D9 | `test_main_stack` |
| REQ-SB-205 | The interrupt chain shall be the sum over priority levels of the deepest handler per level plus one exception frame per nesting level; an unknown priority shall be its own level | ADR-0001 D9 | `test_main_stack` |
| REQ-SB-206 | The main-stack combination (max, sum, or added to each task) shall follow the RTOS profile's interrupt model | ADR-0001 D9 | `test_main_stack` |
| REQ-SB-207 | A stack named by a data symbol shall resolve to exactly one object; a static that is not unique shall be named `file:name`, and a missing or ambiguous symbol shall be an analysis error | ADR-0001 D9 (addendum 2026-11-11) | `test_slice1` |
| **Check and report** ||||
| REQ-SB-301 | A stack shall fail when `required > margin_rule × configured`; `margin_rule` shall default to 0.80 and a project shall be able to override it | ADR-0001 D10 | `test_check` |
| REQ-SB-302 | The recommended size shall be the smallest meeting the rule, rounded up to the profile's alignment, also given in words | ADR-0001 D10 | `test_check` |
| REQ-SB-303 | A stack whose margin exceeds the project's `oversized_above` shall be reported `OVERSIZED` as a warning | ADR-0001 D10 | `test_check` |
| REQ-SB-304 | The report shall give, per stack, required, configured, margin, recommended, status and the worst path with every frame | ADR-0001 D11 | `test_report` |
| REQ-SB-305 | The report shall list every assumption used: annotations, exclusions, and profile values with their layer | ADR-0001 D11 | `test_report` |
| REQ-SB-306 | Output shall be available as text, JSON with a versioned schema, and SARIF | ADR-0001 D11 | `test_report_formats` |
| REQ-SB-307 | A diff against a baseline JSON shall give each stack's change and the changed path | ADR-0001 D11 | `test_diff` |
| REQ-SB-308 | Exit codes shall be `0` pass, `1` check failed, `2` analysis error, `3` usage error | ADR-0001 D11 | `test_cli` |
| REQ-SB-309 | The report shall record the ELF's SHA-256, the tool version and each profile's name and version | ADR-0001 D11 | `test_report` |
| REQ-SB-310 | Excluded path pairs shall never be combined by the walk, and every exclusion shall be listed with its reason | ADR-0001 D12 | `test_exclusions` |
| **Configuration and extension** ||||
| REQ-SB-401 | Profiles shall be TOML data, layered CPU → RTOS → toolchain → project; the report shall show the layer that set each value | ADR-0001 D4 | `test_profiles` |
| REQ-SB-402 | Unknown keys in a profile or project file shall be an error | ADR-0001 D4 | `test_profiles` |
| REQ-SB-403 | Frontends, decoders, resolvers and reporters shall be plugins discovered through Python entry points; built-ins shall use the same mechanism | ADR-0001 D4 | `test_plugins` |
| REQ-SB-404 | The tool shall contain no consumer-specific content | ADR-0001 D15 | review |
| **Quality** ||||
| REQ-SB-501 | Compiler-output parsers shall be strict: an unknown construct shall be an error, never skipped | ADR-0001 D13 | `test_parsers` |
| REQ-SB-502 | Each supported compiler version shall have its own parser fixtures | ADR-0001 D13 | `test_parsers` |
| REQ-SB-503 | Every corpus program shall match its golden frames, edges and targets at `-O0`, `-O2` and `-Os` with every supported compiler | ADR-0001 D14 | corpus CI |
| REQ-SB-504 | For every corpus entry point, the static result shall be ≥ the stack measured under QEMU with a painted stack | ADR-0001 D14 | corpus CI |
