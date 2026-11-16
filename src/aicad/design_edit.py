"""Deterministic edits to agent-written design scripts (no AI).

A design is a chain of recorded steps:

    part = fw.feature("Base plate", Box(...))
    part = fw.feature("Top chamfer", chamfer(...))
    for ...: part -= ...                         # code of the next step
    part = fw.feature("Mounting holes (4x)", part)

The code of a step is every top-level statement after the previous recorded step, up to and including its own
fw.feature call. Deleting a step removes exactly those statements, but only when nothing later uses a value defined
in them. The caller verifies the result against the suppressed model, so a wrong edit can never slip through.
"""

from __future__ import annotations

import ast

MANUAL_START = "# --- Formwright manual features"


class DesignEditError(ValueError):
    """The edit can't be made deterministically; the message is plain language for the user."""


def _feature_call(node: ast.AST) -> ast.Call | None:
    value = getattr(node, "value", None)
    if not isinstance(value, ast.Call):
        return None
    f = value.func
    if not (isinstance(f, ast.Attribute) and f.attr == "feature" and isinstance(f.value, ast.Name)
            and f.value.id in ("fw", "_fw")):
        return None
    if not value.args or not isinstance(value.args[0], ast.Constant) or not isinstance(value.args[0].value, str):
        return None
    kind = next((k.value for k in value.keywords if k.arg == "kind"), None)
    if kind is not None and not (isinstance(kind, ast.Constant) and kind.value == "feature"):
        return None
    return value


def feature_steps(source: str) -> list[tuple[int, str]]:
    """(top-level statement index, feature name) of every recorded design step, in order."""
    body = ast.parse(source).body
    out = []
    for i, st in enumerate(body):
        call = _feature_call(st)
        if call is not None and isinstance(st, (ast.Assign, ast.Expr)):
            out.append((i, str(call.args[0].value)))  # type: ignore[union-attr]
    return out


def _stored(nodes: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for n in nodes:
        for x in ast.walk(n):
            if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                names.add(x.id)
            elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(x.name)
            elif isinstance(x, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in x.names)
    return names


def _loaded(nodes: list[ast.stmt]) -> set[str]:
    return {x.id for n in nodes for x in ast.walk(n) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}


def delete_step(source: str, name: str) -> str:
    """The script with the code of design step `name` removed (manual-features block untouched)."""
    cut = source.index(MANUAL_START) if MANUAL_START in source else len(source)
    base, tail = source[:cut], source[cut:]
    tree = ast.parse(base)
    body = tree.body
    steps = feature_steps(base)
    hits = [i for i, n in steps if n == name]
    if not hits:
        raise DesignEditError(f"“{name}” isn't a separate step of the design")
    if len(hits) > 1:
        raise DesignEditError(f"“{name}” is recorded more than once, so it can't be removed on its own")
    k = hits[0]
    before = [i for i, _ in steps if i < k]
    if not before:
        raise DesignEditError(f"“{name}” is the base feature; every other feature is built on it")
    p = before[-1]
    target, prev = body[k], body[p]

    def chain_var(st: ast.stmt) -> str | None:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            return st.targets[0].id
        return None

    var = chain_var(target)
    if var is None or chain_var(prev) != var:
        raise DesignEditError(f"“{name}” isn't built as a simple step on the previous feature")
    segment = body[p + 1:k + 1]
    later = body[k + 1:]
    shared = (_stored(segment) - {var}) & _loaded(later)
    if shared:
        raise DesignEditError(f"later features use values defined in “{name}” ({', '.join(sorted(shared))})")
    lines = base.splitlines(keepends=True)
    first = segment[0].lineno - 1
    while first > 0 and lines[first - 1].lstrip().startswith("#"):  # comments that introduce the step
        first -= 1
    last = segment[-1].end_lineno or segment[-1].lineno
    return "".join(lines[:first] + lines[last:]) + tail
