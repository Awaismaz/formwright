"""Shared test setup."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _no_live_visual_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """PD-73: the visual assembly check calls a vision model after every smart assembly and integration. Tests never
    spend tokens: it is off unless a test turns it on (``tests/test_assembly_visual.py`` does, with a stub)."""
    monkeypatch.setenv("FW_ASSEMBLY_VISUAL_CHECK", "0")


@pytest.fixture(autouse=True, scope="module")
def _reap_cad_workers() -> Iterator[None]:
    """Each test app keeps warm CAD workers (~300-500 MB each) keyed by project or org; across a session they piled up
    to ~16 processes and hung the founder's PC (2026-11-19). Kill them after every test module."""
    yield
    from aicad.agent import worker as bworker
    from aicad.assembly import worker as aworker
    from aicad.drawing import worker as dworker

    for mod in (bworker, aworker, dworker):
        mod.kill_all()
