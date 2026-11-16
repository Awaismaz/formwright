"""Engineering Advisor: deterministic, unit-safe engineering calculators with cited sources, load cases,
failure-mode review, tolerance stack-ups and engineer sign-off.

Advice levels follow docs/VALIDATION.md §4. Nothing in this package validates a design.
"""

from aicad.engineering import calc_fasteners, calc_machine, calc_structures  # noqa: F401  (registers calculators)
from aicad.engineering.core import LEVELS, REGISTRY, InputError, output, run

__all__ = ["LEVELS", "REGISTRY", "InputError", "output", "run"]
