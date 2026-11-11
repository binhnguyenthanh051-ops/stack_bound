"""CLI smoke tests (the analysis itself is covered in test_slice1.py)."""
import pytest

from stack_bound import __version__
from stack_bound.cli import EXIT_USAGE, main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_arguments_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == EXIT_USAGE
