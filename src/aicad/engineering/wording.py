"""ENG-012 guard: never claim validation (or safety, certification, approval) without evidence.

``claims(text)`` finds affirmative claims such as "validated", "certified", "safe for use", "approved for
production". Negated or level-name uses ("not validated", "Validated simulation: not performed", "unvalidated")
are allowed. Every text this module generates is checked by the tests, and free text that users save into
calculation sets and sign-offs is rejected when it makes such a claim, because a signed set travels with the design.
"""

from __future__ import annotations

import re

_CLAIM = re.compile(
    r"\b(validated|validation\s+(?:passed|complete[d]?)|certified|certifies|guaranteed|"
    r"(?:is|are|be|was|deemed)\s+safe\b|safe\s+(?:for|to)\s+(?:use|operate|release|production|manufacture)|"
    r"fit\s+for\s+purpose|approved\s+for\s+(?:production|release|manufacture|use)|fea[- ]validated|"
    r"verified\s+safe)", re.IGNORECASE)
_NEGATION = re.compile(r"(not|never|no|without|un|non-?|cannot|can't|isn't|aren't|is not|are not)\s*$", re.IGNORECASE)
_ALLOWED_AFTER = re.compile(r"^\s*simulation\b", re.IGNORECASE)   # the level name "Validated simulation"


def claims(text: str) -> list[str]:
    """Affirmative validation/safety claims in ``text`` (empty list when there are none)."""
    found: list[str] = []
    for m in _CLAIM.finditer(text or ""):
        before = text[max(0, m.start() - 12):m.start()]
        after = text[m.end():m.end() + 12]
        if _NEGATION.search(before):
            continue
        if m.group(0).lower() == "validated" and _ALLOWED_AFTER.match(after):
            continue
        if text[max(0, m.start() - 2):m.start()].lower().endswith("un"):
            continue
        found.append(m.group(0))
    return found


class ClaimError(ValueError):
    pass


def require_no_claim(text: str, field: str) -> str:
    bad = claims(text)
    if bad:
        raise ClaimError(f"{field}: remove the wording '{bad[0]}'. Formwright calculations are hand-calculation "
                         "methods; they don't validate or certify a design. Describe what was checked instead "
                         "(for example 'meets the required factor of 2.0 per <source>').")
    return text
