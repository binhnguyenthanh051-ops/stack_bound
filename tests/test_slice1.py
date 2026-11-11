"""Slice 1 tests on the committed Cortex-M corpus (tests/corpus, built by tests/corpus/build.sh)."""
from pathlib import Path

import pytest

from stack_bound import analyze, elfread, gcc, project
from stack_bound.cli import main
from stack_bound.errors import AnalysisError

CORPUS = Path(__file__).parent / "corpus"
OUT = CORPUS / "out"
BASE = (CORPUS / "corpus.toml").read_text(encoding="utf-8")


def write_project(tmp_path, text: str) -> Path:
    p = tmp_path / "stack_bound.toml"
    p.write_text(text, encoding="utf-8")
    return p


def run_cli(tmp_path, text: str, capsys, elf: str = "corpus.elf"):
    rc = main([str(OUT / elf), "--su", str(OUT), "--project", str(write_project(tmp_path, text))])
    out = capsys.readouterr()
    return rc, out.out, out.err


@pytest.fixture(scope="module")
def image():
    return elfread.load(OUT / "corpus.elf")


# ---------------------------------------------------------------- parsers

def test_su_parser_reads_windows_paths_and_refuses_bad_lines():
    # @test REQ-SB-501 : .su parser is strict: malformed and dynamic frames are errors
    good = gcc.parse_su("C:\\work\\src\\a.c:12:5:foo\t48\tstatic\n", "a.su")
    assert (good[0].file, good[0].line, good[0].col, good[0].name, good[0].frame) == ("a.c", 12, 5, "foo", 48)
    with pytest.raises(AnalysisError, match="not a -fstack-usage line"):
        gcc.parse_su("garbage\n", "a.su")
    with pytest.raises(AnalysisError, match="dynamic"):
        gcc.parse_su("a.c:1:1:vla\t32\tdynamic,bounded\n", "a.su")


def test_ci_parser_reads_gcc_graphs_and_refuses_unknown_records():
    # @test REQ-SB-501 : .ci parser is a real grammar; unknown records are errors
    edges = gcc.parse_ci((OUT / "tasks.ci").read_text(encoding="utf-8"), "tasks.ci")
    assert ("verify", gcc.INDIRECT, "../src/tasks.c:33:12") in [(e.source, e.target, e.loc) for e in edges]
    assert ("task_a", "../src/tasks.c:helper") in [(e.source, e.target) for e in edges]
    with pytest.raises(AnalysisError, match="unknown record 'region'"):
        gcc.parse_ci('graph: { title: "x" region: { title: "r" } }', "x.ci")
    with pytest.raises(AnalysisError, match="unexpected text"):
        gcc.parse_ci('graph: { title: "x" node: { title: "a" } } ;;', "x.ci")


# ---------------------------------------------------------------- the ELF

def test_refuses_an_elf_without_dwarf_or_symbols():
    # @test REQ-SB-001 : an ELF with no DWARF or no symbol table is refused, naming what is missing
    with pytest.raises(AnalysisError, match="no DWARF"):
        elfread.load(OUT / "corpus_nodebug.elf")
    with pytest.raises(AnalysisError, match="no symbol table"):
        elfread.load(OUT / "corpus_stripped.elf")


def test_inventory_has_every_function_including_assembly_and_same_name_statics(image):
    # @test REQ-SB-002 : every STT_FUNC symbol is in the inventory
    names = sorted(f.name for f in image.functions.values())
    assert names.count("helper") == 2
    assert {"asm_leaf", "crypto_mac", "task_a", "verify", "Reset_Handler"} <= set(names)
    assert all(a % 2 == 0 for a in image.functions)             # Thumb bit cleared


def test_same_name_statics_get_their_own_frames(image):
    w = gcc.load_dir(OUT)
    proj = project.load(write_project_static(BASE))
    analyze.attach_frames(image, w, proj)
    frames = {f.decl[0]: f.frame for f in image.by_name("helper")}
    assert frames == {"tasks.c": 32, "util.c": 160}


def write_project_static(text):                    # module-scope helper for fixtures without tmp_path
    import tempfile
    d = Path(tempfile.mkdtemp())
    p = d / "stack_bound.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_address_taken_comes_from_the_binary(image):
    names = {image.functions[a].name for a in image.address_taken}
    assert "crypto_mac" in names                    # stored in g_oracle (.rodata)
    assert "unbound_target" not in names and "helper" not in names


# ---------------------------------------------------------------- the check

def test_report_task_stacks_through_the_listed_pointer(tmp_path, capsys):
    # @test REQ-SB-202 : required = deepest path + profile switch frame
    # @test REQ-SB-301 : fails when required > margin x configured, margin defaults to 0.80
    # @test REQ-SB-302 : recommended size meets the rule, rounded to the alignment, also in words
    # @test REQ-SB-304 : per-stack fields and the worst path with every frame
    # @test REQ-SB-308 : exit 1 when a check fails
    rc, out, _ = run_cli(tmp_path, BASE, capsys)
    assert rc == 1
    assert "task task_a            768 B      1024 B    75%     960 B (240 w)  ok" in out
    assert "task task_b            760 B       256 B   297%     952 B (238 w)  FAIL" in out
    assert "~> crypto_mac 520 B   [listed: g_oracle.mac = crypto_mac (crypto.c)]" in out
    assert "560 B + 208 B switch frame" in out


def test_passing_project_exits_zero_and_records_its_inputs(tmp_path, capsys):
    # @test REQ-SB-308 : exit 0 when every stack passes
    # @test REQ-SB-309 : the report records the ELF hash, tool version and profile name/version
    # @test REQ-SB-305 : every assumption is listed, with the layer that set it
    text = BASE.replace('entry = "task_b"\nstack = "s_stack_b"', 'entry = "task_b"\nstack_bytes = 2048')
    text = 'margin_rule = 0.9\n' + text
    rc, out, _ = run_cli(tmp_path, text, capsys)
    assert rc == 0
    assert "stack_bound 0.1.0 | corpus.elf (sha256 " in out and "profile cortex-m-freertos v1" in out
    assert "margin rule 0.90 [project]" in out
    assert "indirect verify -> crypto_mac: g_oracle.mac = crypto_mac (crypto.c)" in out
    assert "switch frame 208 B (FPU) / 72 B [profile cortex-m-freertos]" in out


def test_an_unbound_function_pointer_is_an_error_not_a_smaller_number(tmp_path, capsys):
    # @test REQ-SB-308 : exit 2 on an analysis error
    text = BASE.split("[[indirect]]")[0]
    rc, out, err = run_cli(tmp_path, text, capsys)
    assert rc == 2 and out == ""
    assert "verify: indirect call at ../src/tasks.c:33:12 has no binding" in err


def test_a_listed_target_must_be_address_taken(tmp_path, capsys):
    text = BASE.replace('targets = ["crypto_mac"]', 'targets = ["unbound_target"]')
    rc, _, err = run_cli(tmp_path, text, capsys)
    assert rc == 2 and "unbound_target is never address-taken" in err


def test_recursion_is_refused_with_its_edges(tmp_path, capsys):
    # @test REQ-SB-151 : the cycle is detected
    # @test REQ-SB-152 : and reported as an error listing its edges with their provenance
    rc, _, err = run_cli(tmp_path, BASE + '\n[[task]]\nentry = "task_r"\nstack_bytes = 512\n', capsys)
    assert rc == 2 and "recursion: fact -[call]-> fact" in err


def test_a_function_with_no_frame_is_named_until_annotated(tmp_path, capsys):
    # @test REQ-SB-002 : a function on a path with no frame from any witness is an error naming it
    # @test REQ-SB-305 : the annotation then appears among the assumptions
    task_m = '\n[[task]]\nentry = "task_m"\nstack_bytes = 512\n'
    rc, _, err = run_cli(tmp_path, BASE + task_m, capsys)
    assert rc == 2 and "asm_leaf: no frame from any witness" in err
    frames = '\n[frames]\nasm_leaf = { bytes = 12, source = "leaf.S: push {r4, r5, lr}" }\n'
    rc, out, _ = run_cli(tmp_path, BASE + task_m + frames, capsys)
    assert rc == 1                                   # task_b still fails; task_m is analysed
    assert "frame asm_leaf = 12 B: leaf.S: push {r4, r5, lr}" in out


def test_unknown_keys_are_refused(tmp_path, capsys):
    # @test REQ-SB-402 : unknown keys in a project file are errors
    rc, _, err = run_cli(tmp_path, BASE.replace('stack = "s_stack_a"', 'stack = "s_stack_a"\nstak = 1'), capsys)
    assert rc == 2 and "unknown key(s) stak" in err


def test_usage_errors_exit_3(tmp_path, capsys):
    # @test REQ-SB-308 : exit 3 on a usage error
    with pytest.raises(SystemExit) as exc:
        main([str(OUT / "corpus.elf")])
    assert exc.value.code == 3
    assert main([str(tmp_path / "missing.elf"), "--su", str(OUT), "--project", str(CORPUS / "corpus.toml")]) == 3
