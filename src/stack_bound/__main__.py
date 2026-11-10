"""Allows `python -m stack_bound` from a checkout or an install."""
import sys

from stack_bound.cli import main

sys.exit(main())
