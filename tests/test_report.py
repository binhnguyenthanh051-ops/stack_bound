"""Report tests: one model, rendered as text, JSON and HTML (ADR-0001 D11 + addendum 2026-11-11)."""
import copy
import json
import re
from pathlib import Path

import pytest

from stack_bound import analyze, elfread, gcc, project, report
from stack_bound.cli import main

CORPUS = Path(__file__).parent / "corpus"
OUT = CORPUS / "out"


@pytest.fixture(scope="module")
def m():
    image = elfread.load(OUT / "corpus.elf")
    proj = project.load(CORPUS / "corpus.toml")
    return report.model(image, proj, analyze.run(image, gcc.load_dir(OUT), proj))


def test_json_round_trips_and_carries_its_schema(m):
    # (part of REQ-SB-306: JSON with a versioned schema; SARIF comes later)
    data = json.loads(report.json(m))
    assert data == m and data["schema"] == "stack_bound.report/1"
    a, b = data["stacks"]
    assert (a["entry"], a["required"], a["configured"], a["recommended_words"], a["status"]) == ("task_a", 768, 1024, 240, "ok")
    assert b["status"] == "FAIL"
    assert [s["edge"] for s in a["path"]] == ["entry", "call", "listed"]
    assert a["path"][2]["reason"].startswith("listed: g_oracle.mac")


def test_text_is_rendered_from_the_model(m):
    changed = copy.deepcopy(m)
    changed["stacks"][0]["entry"] = "renamed"
    assert "task renamed" in report.text(changed) and "task renamed" not in report.text(m)


def test_html_is_one_self_contained_page(m):
    # @test REQ-SB-311 : self-contained: no script, nothing fetched from anywhere
    page = report.html(m)
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert "<script" not in page and "<link" not in page and "@import" not in page
    assert not re.search(r"""(src|href)=["']?(https?:)?//""", page) and "url(" not in page


def test_html_shows_each_stack_its_margin_and_its_worst_path(m):
    # @test REQ-SB-311 : per stack a bar against configured with the margin line, the path, the assumptions
    page = report.html(m)
    assert "1 of 2 stacks fail" in page
    # task_a: 1024 B configured is the whole track, so the 80% rule line sits at 80% and the end at 100%
    a = page.split('id="task-task_a"')[1].split("</article>")[0]
    assert 'class="rule" style="left:80.00%"' in a and 'class="end" style="left:100.00%"' in a
    assert a.count("<tr class=") == 4                    # task_a, verify, crypto_mac, switch frame
    assert "function pointer, listed: g_oracle.mac = crypto_mac (crypto.c)" in a
    assert "seg path over" in page                       # task_b runs past its 256 B stack
    assert "margin rule 0.80 [tool default]" in page


def test_html_escapes_everything_it_shows(m):
    # @test REQ-SB-311 : text from the project file can't become markup
    evil = copy.deepcopy(m)
    evil["stacks"][0]["entry"] = "<img onerror=x>"
    evil["assumptions"][0]["text"] = "a <b>bold</b> & claim"
    page = report.html(evil)
    assert "<img onerror" not in page and "&lt;img onerror=x&gt;" in page
    assert "a &lt;b&gt;bold&lt;/b&gt; &amp; claim" in page


def test_cli_writes_json_and_html_next_to_the_text(tmp_path, capsys):
    j, h = tmp_path / "r.json", tmp_path / "r.html"
    rc = main([str(OUT / "corpus.elf"), "--su", str(OUT), "--project", str(CORPUS / "corpus.toml"),
               "--json", str(j), "--html", str(h)])
    assert rc == 1 and "task task_b" in capsys.readouterr().out
    assert json.loads(j.read_text(encoding="utf-8"))["schema"] == report.SCHEMA
    assert "Stack report · corpus.elf" in h.read_text(encoding="utf-8")
