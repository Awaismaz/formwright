"""Shared test setup."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_live_visual_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """PD-73: the visual assembly check calls a vision model after every smart assembly and integration. Tests never
    spend tokens: it is off unless a test turns it on (``tests/test_assembly_visual.py`` does, with a stub)."""
    monkeypatch.setenv("FW_ASSEMBLY_VISUAL_CHECK", "0")
