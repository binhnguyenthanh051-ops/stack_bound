"""Path helpers that behave the same on every host.

A build made on Windows writes `C:\\src\\a.c` into .su, .ci and DWARF; the analysis may run on Linux
(CI) or Windows. os.path.basename splits only on the host's separator, so it can't be used here.
"""
import re


def base(path: str) -> str:
    """Last component of a path written with / or \\ separators."""
    return re.split(r"[\\/]", path)[-1]
