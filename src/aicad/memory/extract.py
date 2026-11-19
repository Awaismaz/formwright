"""Deterministic capture of standing instructions from what a person types in the design chat (no AI).

Two kinds of sentence are kept, conservatively (a missed statement costs nothing; a wrong one would steer every
later part, so only explicit wording counts):

- **project decisions**: the sentence addresses the whole project ("all fasteners M6 ISO 4762", "use 6061-T6 for
  every part", "across this project, tolerances to ISO 2768-m"). Only when the part is in a project.
- **personal rules**: the person states a habit ("always add 0.5 mm chamfers to outside edges", "never use
  countersunk screws", "I prefer metric fine threads").

Questions are never captured. Bracketed context the app appends to a message (selection, design state) is ignored.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

MAX_TEXT = 200

_SPLIT = re.compile(r"(?<=[.!;?])\s+|\n+")
_PERSONAL = re.compile(r"\b(always|never|by default|i (?:always|usually|normally|prefer|like to)|i'd rather|"
                       r"my (?:standard|default|preference) is|prefer(?:ably)?)\b", re.IGNORECASE)
_PROJECT = re.compile(r"\b(?:(?:all|every|each)\s+(?:of\s+)?(?:the\s+|our\s+)?(?:parts?|fasteners?|bolts?|screws?|"
                      r"holes?|components?|pieces?|brackets?|covers?|plates?)|(?:for|in|across|throughout)\s+(?:this|"
                      r"the|our)\s+(?:project|assembly|product|program)|project[- ]wide)\b", re.IGNORECASE)
_CATEGORY = (
    ("fastener", re.compile(r"\b(M\d{1,2}(?:x\d(?:\.\d+)?)?|ISO\s?4762|ISO\s?4017|ISO\s?4014|ISO\s?10642|DIN\s?912|"
                            r"DIN\s?933|bolts?|screws?|fasteners?|nuts?|washers?|cap screws?|SHCS)\b", re.IGNORECASE)),
    ("material", re.compile(r"\b(6061|6082|7075|5083|aluminium|aluminum|steel|stainless|304|316L?|S235|S355|C45|"
                            r"brass|bronze|copper|titanium|ABS|PLA|PETG|nylon|PA\d+|POM|delrin|acetal|PEEK|"
                            r"polycarbonate|PC|cast iron)\b", re.IGNORECASE)),
    ("tolerance", re.compile(r"\b(ISO\s?2768(?:-\w)?|tolerances?|H7|h6|g6|IT\d{1,2}|fits?)\b", re.IGNORECASE)),
    ("units", re.compile(r"\b(inch(?:es)?|imperial|metric|millimet(?:re|er)s?)\b", re.IGNORECASE)),
    ("standard", re.compile(r"\b(ISO\s?\d+|DIN\s?\d+|ANSI|ASME\s?Y14|BS\s?\d+)\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class Statement:
    scope: str  # "project" | "personal"
    text: str
    category: str

    @property
    def key(self) -> str:
        return "rule:" + hashlib.sha1(normalise(self.text).encode()).hexdigest()[:12]


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def category(text: str) -> str:
    for name, rx in _CATEGORY:
        if rx.search(text):
            return name
    return "other"


def _user_text(prompt: str) -> str:
    """The person's own words: drop the bracketed blocks the app appends (selection, design state, images)."""
    return re.split(r"\n\n\[", prompt, maxsplit=1)[0]


def _clean(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -•*\t")
    s = re.sub(r"^(?:also|and|please|pls|ok|okay|note|fyi)[,:]?\s+", "", s, flags=re.IGNORECASE)
    return s[:1].upper() + s[1:] if s else s


def statements(prompt: str, in_project: bool) -> list[Statement]:
    out: list[Statement] = []
    seen: set[str] = set()
    for raw in _SPLIT.split(_user_text(prompt)):
        s = _clean(raw)
        if len(s) < 8 or len(s) > MAX_TEXT or s.endswith("?") or re.match(r"^(?:can|could|should|would|what|why|how|"
                                                                          r"is|are|do|does)\b", s, re.IGNORECASE):
            continue
        s = s.rstrip(".;")
        scope = None
        if in_project and _PROJECT.search(s) and category(s) != "other":
            scope = "project"
        elif _PERSONAL.search(s):
            scope = "personal"
        if scope is None:
            continue
        n = normalise(s)
        if n in seen:
            continue
        seen.add(n)
        out.append(Statement(scope=scope, text=s, category=category(s)))
    return out[:5]
