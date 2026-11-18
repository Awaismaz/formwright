"""Static checks of every Python file in an imported package, BEFORE anything runs.

Every file (model, helper modules, every revision's model) goes through the runner's import tripwire, the same one
the design agent's scripts pass (R-SEC-05). Files from another workspace — or whose signature does not verify — also
pass a strict allow-list (``strict=True``):

- imports only from build123d (top level), ``aicad.fw`` / ``aicad.toolbox``, a short list of pure standard-library
  modules, and the package's own helper modules; no relative imports;
- no file or network access names (``import_step``, ``export_stl``, ``Mesher``, ``open``, ...), no attribute that
  reads, writes, imports or exports (``.write_text``, ``.export_brep``, ...);
- no introspection escapes: dunder attributes and names, ``getattr``/``globals``/``vars``..., private attributes,
  string constants containing ``__`` (``str.format`` field access), attributes of ``fw``/``toolbox``/``build123d``
  that are modules.

This is defence in depth on top of the build worker's process isolation; it is not a sandbox (PD-10 / R-SEC-05).
"""

from __future__ import annotations

import ast
import re
import types
from typing import Any

from aicad.agent.runner import ScriptRejected, tripwire
from aicad.native import NativeFormatError

SAFE_STDLIB = {"math", "cmath", "itertools", "functools", "collections", "typing", "dataclasses", "enum",
               "fractions", "decimal", "statistics", "copy", "operator", "string", "re", "json", "random",
               "__future__"}
APP_MODULES = {"aicad": {"fw", "toolbox"}, "aicad.fw": None, "aicad.toolbox": None, "build123d": None}
BLOCKED_NAMES = {
    "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "help", "exit", "quit", "memoryview",
    "__import__", "__builtins__", "__loader__", "__spec__", "__file__", "open", "exec", "eval", "compile", "input",
    "Mesher", "Export2D", "ExportDXF", "ExportSVG",
}
_IO_NAME = re.compile(r"^(import|export)_|^(Import|Export)[A-Z]")
_IO_ATTR = re.compile(r"^([Ii]mport|[Ee]xport|[Ww]rite|[Rr]ead|[Oo]pen|[Ss]ave|[Ll]oad|unlink|remove|rmdir|mkdir|chmod|"
                      r"chown|rename|system|popen|spawn|exec|tofile|fromfile)(?=$|[_A-Z0-9])")
_HELPER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")


def _module_obj(name: str) -> Any:
    import importlib

    try:
        return importlib.import_module(name)  # our own trusted packages only (allow-listed above)
    except ImportError:
        return None


def _reject(where: str, why: str) -> None:
    raise NativeFormatError(f"{where}: {why}. Files from another workspace may only describe geometry.")


def check_script(source: str, where: str, *, strict: bool, helpers: set[str]) -> None:
    """Raise NativeFormatError if the script must not run. ``helpers``: module names of the package's own .py files."""
    try:
        tripwire(source)
    except ScriptRejected as e:
        raise NativeFormatError(f"{where}: {e}. The file was rejected; nothing was run.") from None
    except (SyntaxError, ValueError):
        raise NativeFormatError(f"{where}: not a valid model script.") from None
    if strict:
        _strict(ast.parse(source), where, helpers)


def _strict(tree: ast.AST, where: str, helpers: set[str]) -> None:
    aliases: dict[str, str] = {}  # local name -> app module it is bound to (aicad.fw, aicad.toolbox, build123d)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split(".")[0]
                if a.name in SAFE_STDLIB or root in SAFE_STDLIB and a.name.startswith("collections."):
                    continue
                if a.name in helpers:
                    continue
                if a.name in ("aicad.fw", "aicad.toolbox") and a.asname:
                    aliases[a.asname] = a.name
                    continue
                _reject(where, f"importing '{a.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:
                _reject(where, "relative imports are not allowed")
            if mod in SAFE_STDLIB or mod.startswith("collections.") or mod in helpers:
                continue
            if mod not in APP_MODULES:
                _reject(where, f"importing from '{mod}' is not allowed")
            allowed = APP_MODULES[mod]
            for a in node.names:
                if a.name == "*":
                    if mod != "build123d":
                        _reject(where, f"'from {mod} import *' is not allowed")
                    continue
                if allowed is not None:
                    if a.name not in allowed:
                        _reject(where, f"importing '{a.name}' from '{mod}' is not allowed")
                    aliases[a.asname or a.name] = f"{mod}.{a.name}"
                    continue
                if a.name.startswith("_") or a.name in BLOCKED_NAMES or _IO_NAME.search(a.name):
                    _reject(where, f"'{a.name}' is not allowed")
                if isinstance(getattr(_module_obj(mod), a.name, None), types.ModuleType):
                    _reject(where, f"'{a.name}' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BLOCKED_NAMES or _IO_NAME.search(node.id) or (node.id.startswith("__") and node.id != "__name__"):
                _reject(where, f"'{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("_"):
                _reject(where, f"access to '.{attr}' is not allowed")
            if _IO_ATTR.search(attr):
                _reject(where, f"'.{attr}' (file access) is not allowed")
            if isinstance(node.value, ast.Name) and node.value.id in aliases:
                target = getattr(_module_obj(aliases[node.value.id]), attr, None)
                if isinstance(target, types.ModuleType):
                    _reject(where, f"'.{attr}' is not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            _reject(where, "text containing '__' is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            _reject(where, "global statements are not allowed")


def helper_names(paths: list[str]) -> set[str]:
    """Module names of top-level helper .py files (other than model.py), validated as plain identifiers that do not
    shadow an allowed module."""
    out = set()
    for p in paths:
        if "/" in p or not p.endswith(".py") or p == "model.py":
            continue
        stem = p[:-3]
        if not _HELPER.fullmatch(stem) or stem in SAFE_STDLIB or stem in ("aicad", "build123d", "model", "OCP"):
            raise NativeFormatError(f"{p}: helper module name is not allowed.")
        out.add(stem)
    return out
