"""ASM-012 golden assembly fixtures FX-04 / FX-05 / FX-06 (original designs, generated for Formwright).

    uv run python -m aicad.fixtures              # rebuild every fixture and run its checks
    uv run python -m aicad.fixtures --write      # regenerate specs/fixtures/<fixture>/assembly.json

The definition files and provenance live in ``specs/fixtures/`` (see its README); tests in
``tests/test_fixtures_asm.py`` rebuild the fixtures and assert every check.
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from aicad.fixtures import fx04_bolted_bracket, fx05_keyed_shaft, fx06_hinged_arm
from aicad.fixtures.harness import Fixture

MODULES: dict[str, ModuleType] = {m.ID: m for m in (fx04_bolted_bracket, fx05_keyed_shaft, fx06_hinged_arm)}
FIXTURES: dict[str, Callable[[], Fixture]] = {k: m.fixture for k, m in MODULES.items()}

__all__ = ["FIXTURES", "MODULES"]
