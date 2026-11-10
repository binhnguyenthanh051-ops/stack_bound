"""Tests for tools/trace_report.py (the repository's own traceability check)."""
from pathlib import Path

import pytest

import trace_report

AT = "@"  # kept apart so this file doesn't carry real tags

ADR_TEXT = """# ADR-0042: Demo decision

**Status:** {status} · **Date:** 2026-11-10

### D1. The first decision
### D2. The second decision
"""

REQ_TEXT = """# Demo requirements

| ID | Requirement | Traces | Verified by |
|---|---|---|---|
| **Group** ||||
| REQ-DEMO-001 | The demo shall work | ADR-0042 D1 | `test_demo` |
| REQ-DEMO-002 | The demo shall also work | ADR-0042 D1, ADR-0042 D2 | `test_demo` |
"""


def make_repo(tmp_path: Path, status: str = "proposed", reqs: str = REQ_TEXT) -> Path:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "requirements").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "ADR-0042-demo.md").write_text(
        ADR_TEXT.format(status=status), encoding="utf-8")
    (tmp_path / "docs" / "requirements" / "demo.md").write_text(reqs, encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


def tag(kind: str, target: str) -> str:
    return f"# {AT}{kind} {target} : demo\n"


def gap_kinds(model) -> set[tuple[str, str]]:
    return {(k, i) for k, i, _ in model.gaps}


def test_proposed_adr_without_tags_is_pending_not_a_gap(tmp_path):
    model = trace_report.build_model(make_repo(tmp_path))
    assert model.gaps == []
    assert {trace_report.state_of(model, r) for r in model.reqs.values()} == {"pending"}


def test_accepted_adr_without_a_gate_is_open_not_a_gap(tmp_path):
    model = trace_report.build_model(make_repo(tmp_path, status="accepted"))
    assert model.gaps == []
    assert {trace_report.state_of(model, r) for r in model.reqs.values()} == {"open"}


def test_gated_area_requires_impl_and_test(tmp_path):
    root = make_repo(tmp_path, status="accepted")
    (root / "pyproject.toml").write_text(
        '[tool.trace_report]\ngates = ["REQ-DEMO-00"]\n', encoding="utf-8")
    (root / "src" / "demo.py").write_text(tag("impl", "REQ-DEMO-001"), encoding="utf-8")
    model = trace_report.build_model(root)
    assert model.gates == ["REQ-DEMO-00"]
    kinds = gap_kinds(model)
    assert ("uncovered", "REQ-DEMO-001") in kinds  # impl but no test
    assert ("uncovered", "REQ-DEMO-002") in kinds  # neither


def test_gate_only_covers_its_prefix(tmp_path):
    root = make_repo(tmp_path, status="accepted")
    (root / "pyproject.toml").write_text(
        '[tool.trace_report]\ngates = ["REQ-DEMO-002"]\n', encoding="utf-8")
    kinds = gap_kinds(trace_report.build_model(root))
    assert ("uncovered", "REQ-DEMO-002") in kinds
    assert ("uncovered", "REQ-DEMO-001") not in kinds


def test_covered_requirement_has_no_gap(tmp_path):
    root = make_repo(tmp_path, status="accepted",
                     reqs=REQ_TEXT.replace(
                         "| REQ-DEMO-002 | The demo shall also work | ADR-0042 D1, ADR-0042 D2 "
                         "| `test_demo` |\n", ""))
    (root / "src" / "demo.py").write_text(tag("impl", "REQ-DEMO-001"), encoding="utf-8")
    (root / "tests" / "test_demo.py").write_text(tag("test", "REQ-DEMO-001"), encoding="utf-8")
    model = trace_report.build_model(root)
    assert model.gaps == []
    assert trace_report.state_of(model, model.reqs["REQ-DEMO-001"]) == "covered"


def test_dangling_tags_are_gaps(tmp_path):
    root = make_repo(tmp_path)
    (root / "src" / "demo.py").write_text(
        tag("impl", "REQ-DEMO-999") + tag("impl", "ADR-0042 D9") + tag("impl", "ADR-0042 D2"),
        encoding="utf-8")
    kinds = gap_kinds(trace_report.build_model(root))
    assert ("dangling", "REQ-DEMO-999") in kinds
    assert ("dangling", "ADR-0042 D9") in kinds
    assert ("dangling", "ADR-0042 D2") not in kinds


def test_trace_to_missing_decision_is_a_gap(tmp_path):
    root = make_repo(tmp_path, reqs=REQ_TEXT.replace("ADR-0042 D1 |", "ADR-0042 D7 |", 1))
    assert ("bad-trace", "REQ-DEMO-001") in gap_kinds(trace_report.build_model(root))


def test_requirement_without_trace_is_a_gap(tmp_path):
    root = make_repo(tmp_path, reqs=REQ_TEXT.replace("ADR-0042 D1 |", "— |", 1))
    assert ("no-trace", "REQ-DEMO-001") in gap_kinds(trace_report.build_model(root))


def test_duplicate_requirement_is_a_gap(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "requirements" / "more.md").write_text(
        "| REQ-DEMO-001 | Again | ADR-0042 D1 | x |\n", encoding="utf-8")
    assert ("duplicate-req", "REQ-DEMO-001") in gap_kinds(trace_report.build_model(root))


def test_check_mode_detects_a_stale_matrix(tmp_path, capsys):
    root = make_repo(tmp_path)
    assert trace_report.main(["--root", str(root)]) == 0
    assert trace_report.main(["--root", str(root), "--check"]) == 0
    (root / "src" / "demo.py").write_text(tag("impl", "REQ-DEMO-001"), encoding="utf-8")
    assert trace_report.main(["--root", str(root), "--check"]) == 1
    assert "stale" in capsys.readouterr().err


def test_render_is_deterministic(tmp_path):
    root = make_repo(tmp_path)
    assert trace_report.render(trace_report.build_model(root)) == \
        trace_report.render(trace_report.build_model(root))


def test_this_repository_has_no_gaps():
    root = Path(__file__).resolve().parent.parent
    model = trace_report.build_model(root)
    assert model.gaps == [], model.gaps
    assert len(model.reqs) >= 54


@pytest.mark.parametrize("text", [
    "| REQ-SB-001 | x | ADR-0001 D1 | y |",
    "|REQ-SB-001|x|ADR-0001 D1|y|",
])
def test_requirement_row_formats(text):
    m = trace_report.REQ_ROW_RE.match(text)
    assert m and m.group(1) == "REQ-SB-001"
