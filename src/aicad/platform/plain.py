"""Build failures in plain engineering words for the UI (STU-05).

The runner records failures as `"<ExceptionType>: <message>"`; this turns them into a sentence a designer can act
on. Exception and function names, file names and Python never reach the user."""

from __future__ import annotations

import re
from typing import Any

CHECK_WORDS = {
    "CHK-02": "the result is not a single valid solid",
    "CHK-03": "the result has open or non-manifold edges",
    "CHK-04": "the overall size no longer matches the design's stated size",
    "CHK-05": "the volume no longer matches the design's stated volume",
    "CHK-06": "the hole and cylinder count changed",
    "CHK-07": "the exported STEP didn't read back identically",
    "CHK-08": "the rebuild wasn't repeatable",
}

_KERNEL = re.compile(r"StdFail|Standard_|BRep|TopoDS|gp_|OCP|OCC|Geom_|BOPAlgo|null shape|NotDone", re.IGNORECASE)
_PY = re.compile(r"^(?:[A-Za-z_][\w.]*Error|[A-Za-z_][\w.]*Exception|ScriptRejected|AssertionError|StopIteration)$")
_MANUAL = re.compile(r"manual feature '(?P<name>[^']*)' failed: (?P<msg>.*)", re.DOTALL)
_FILLET = re.compile(r"Failed creating a fillet with radius of (?P<r>[\d.]+)", re.IGNORECASE)


def _clean(msg: str) -> str:
    msg = re.sub(r"`?\b[A-Za-z_][\w.]*\(\)`?", "", msg)  # function names such as max_fillet()
    msg = re.sub(r"\s+", " ", msg).strip(" .;:,—-")
    return msg


def _sentence(msg: str) -> str:
    msg = _clean(msg)
    return msg[:1].upper() + msg[1:] if msg else msg


def kernel_message(raw: str) -> str:
    """One failure message (no exception prefix) in plain words."""
    m = _FILLET.search(raw)
    if m:
        return f"a fillet of R{float(m['r']):g} mm no longer fits; try a smaller radius"
    if _KERNEL.search(raw) or not raw.strip():
        return "the geometry kernel could not compute the shape with these values"
    return _clean(raw)


def build_error(error: str | None, checks: list[dict[str, Any]] | None = None) -> str:
    """Why a build failed, as a plain sentence (no trailing full stop)."""
    if error:
        head, sep, rest = error.partition(": ")
        if head == "rejected":
            return _sentence(rest)
        if sep and _PY.match(head):
            kind, msg = head, rest
        else:
            kind, msg = "", error
        m = _MANUAL.match(msg)
        if m:
            return f"“{m['name']}” couldn't be built: {kernel_message(m['msg'])}"
        if kind in ("NameError", "TypeError", "AttributeError", "IndexError", "KeyError", "ZeroDivisionError",
                    "SyntaxError", "ImportError", "ModuleNotFoundError", "RecursionError"):
            return "The design couldn't be rebuilt with these values"
        return _sentence(kernel_message(msg))
    failed = [CHECK_WORDS.get(c["id"], "a geometry check failed") for c in (checks or [])
              if c.get("gating") and not c.get("passed")]
    if failed:
        return _sentence("; ".join(dict.fromkeys(failed)))
    return "The model couldn't be built"
