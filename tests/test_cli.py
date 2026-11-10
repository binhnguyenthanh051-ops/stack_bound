"""Smoke tests for the placeholder CLI."""
import pytest

from stack_bound import __version__
from stack_bound.cli import EXIT_USAGE, main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_elf_is_a_usage_error():
    assert main([]) == EXIT_USAGE


def test_analysis_not_implemented_yet(capsys):
    assert main(["firmware.elf"]) == EXIT_USAGE
    assert "not implemented" in capsys.readouterr().err
