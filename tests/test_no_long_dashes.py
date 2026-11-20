"""House style: no long dashes. The em dash (U+2014) and the en dash (U+2013) are banned from every text file under
src/aicad: code, comments, docstrings, prompts, user-facing messages, templates and data alike. Write a full stop,
comma, colon, semicolon, parentheses or "to"; a table cell with no value shows "-". Code that has to recognise these
characters in input writes them as escapes ("\\u2014", "\\u2013")."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "aicad"
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".html", ".css", ".js"}
BANNED = ("\u2014", "\u2013")


def _text_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*")
                  if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in p.parts)


def test_scope_covers_the_package():
    files = {p.relative_to(SRC).as_posix() for p in _text_files()}
    for must in ("agent/prompt.py", "agent/session.py", "toolbox.py", "drawing/generate.py",
                 "viewer/static/index.html"):
        assert must in files
    assert len(files) > 100


def test_no_em_or_en_dash_in_src():
    hits = []
    for p in _text_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if any(ch in line for ch in BANNED):
                hits.append(f"{p.relative_to(SRC).as_posix()}:{i}: {line.strip()[:120]}")
    assert not hits, "long dashes found:\n" + "\n".join(hits)
