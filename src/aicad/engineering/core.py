"""Calculator framework: typed, unit-checked inputs, shown working, cited sources, advice levels, attributed safety
factors.

A calculator is a pure function ``f(inputs: dict) -> Work`` registered with a schema (``Param`` list). ``run()``
validates and converts the raw API inputs (pint, see ``units``), calls the function, and packages the result with
the calculator's references, assumptions, version and advice level. Results never claim validation: a calculator
result is a *Preliminary estimate* until an engineer signs the calculation set it belongs to (then *Verified
calculation*, VALIDATION §4). *Validated simulation* is never produced by this module.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from aicad.engineering import units

# VALIDATION §4 advice levels (ENG-007), lowest to highest evidence
LEVELS: dict[str, dict[str, str]] = {
    "recommended_check": {"label": "Recommended check",
                          "meaning": "Something an engineer should look at; no calculation behind it yet."},
    "preliminary_estimate": {"label": "Preliminary estimate",
                             "meaning": "Hand-calculation method with stated assumptions; not reviewed."},
    "verified_calculation": {"label": "Verified calculation",
                             "meaning": "Deterministic, unit-tested calculator whose inputs and results a named "
                                        "engineer has reviewed and signed."},
    "validated_simulation": {"label": "Validated simulation",
                             "meaning": "External validated solver with correlation evidence. Not produced by "
                                        "Formwright."},
}

ENGINE_VERSION = "eng-1.0.0"
SHIGLEY_REF = "Budynas & Nisbett, Shigley's Mechanical Engineering Design, 11th ed. (McGraw-Hill, 2020)"


class InputError(ValueError):
    """A calculator input is missing, of the wrong unit, or out of range (HTTP 422)."""


@dataclass
class Column:
    key: str
    label: str
    kind: str = "length"          # unit kind, or "text" / "enum"
    unit: str = ""                # default display unit
    default: Any = None
    options: list[dict[str, str]] | None = None
    min: float | None = None


@dataclass
class Param:
    key: str
    label: str
    kind: str                     # unit kind (units.KINDS) or "enum" | "bool" | "text" | "table"
    default: Any = None
    unit: str = ""                # default display unit (pint expression)
    min: float | None = None
    max: float | None = None
    exclusive_min: bool = False
    help: str = ""
    group: str = "Inputs"
    optional: bool = False
    options: list[dict[str, str]] | None = None   # enum: [{"value", "label"}]
    columns: list[Column] | None = None           # table
    show_if: dict[str, list[Any]] | None = None   # only relevant when another input has one of these values
    prefill: str | None = None                    # hint of what the model can supply


@dataclass
class Step:
    label: str
    equation: str
    substitution: str
    value: float | str | None
    unit: str = ""
    ref: str = ""


@dataclass
class Output:
    key: str
    label: str
    value: float | str | None
    kind: str = "ratio"
    unit: str = ""
    primary: bool = False


@dataclass
class Check:
    """A comparison of a result against a criterion. Safety-factor checks always carry the SF source (ENG-005)."""
    label: str
    achieved: float | None
    required: float | None = None
    source: str = ""
    passed: bool | None = None
    basis: str = ""


@dataclass
class Work:
    steps: list[Step] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sf_used: bool = False          # a check compared a result against the required safety factor

    def step(self, label: str, equation: str, substitution: str, value: float | str | None, unit: str = "",
             ref: str = "") -> float | str | None:
        self.steps.append(Step(label, equation, substitution, _clean(value), unit, ref))
        return value

    def out(self, key: str, label: str, value: float | str | None, kind: str = "ratio", unit: str = "",
            primary: bool = False) -> None:
        self.outputs.append(Output(key, label, _clean(value), kind, unit or units.KINDS.get(kind, units.KINDS["ratio"]).canonical,
                                   primary))

    def sf_check(self, label: str, achieved: float, required: float | None, source: str, basis: str) -> None:
        self.sf_used = True
        passed = None if required is None else bool(achieved >= required - 1e-12)
        self.checks.append(Check(label, _clean(achieved), required, source, passed, basis))  # type: ignore[arg-type]

    def check(self, label: str, passed: bool, basis: str, achieved: float | None = None) -> None:
        self.checks.append(Check(label, _clean(achieved), None, "", bool(passed), basis))  # type: ignore[arg-type]


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v):
            return None
        if math.isinf(v):
            return "∞"
    return v


@dataclass
class Calculator:
    id: str
    name: str
    category: str
    summary: str
    inputs: list[Param]
    func: Callable[[dict[str, Any]], Work]
    references: list[str]
    assumptions: list[str]
    verified_against: list[str]            # published examples / derivations the unit tests reproduce
    version: str = "1.0.0"
    keywords: list[str] = field(default_factory=list)
    safety_factor: bool = False            # adds required SF + mandatory source inputs (ENG-005)
    prefill: list[str] = field(default_factory=list)   # what the project link can pre-fill

    def schema(self) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k not in ("func",)}
        d["inputs"] = [_param_schema(p) for p in self.all_inputs()]
        d["level"] = "preliminary_estimate"
        return d

    def all_inputs(self) -> list[Param]:
        if not self.safety_factor:
            return self.inputs
        return [*self.inputs, *SF_PARAMS]


SF_PARAMS = [
    Param("sf_required", "Required safety factor", "ratio", None, min=1.0, group="Safety factor", optional=True,
          help="The minimum factor of safety your design code, customer or company standard requires. Needed "
               "whenever the calculator checks a result against it."),
    Param("sf_source", "Safety factor source", "text", "", group="Safety factor", optional=True,
          help="Where the required factor comes from, e.g. a design code clause, customer specification or "
               "company standard. Needed with the factor; results always show it next to the factor."),
]

# Load inputs whose schema default is an illustrative textbook value (MAKE-19): a non-zero default of these kinds
# is an *example*, flagged until the user replaces or confirms it. Sign-off is blocked while any remain.
LOAD_KINDS = {"force", "moment", "line_load", "speed"}


def _is_load(p: Param) -> bool:
    if p.kind == "table":
        return any(c.kind in LOAD_KINDS for c in p.columns or [])
    return p.kind in LOAD_KINDS


def _param_schema(p: Param) -> dict[str, Any]:
    d = asdict(p)
    if p.kind in units.KINDS:
        k = units.KINDS[p.kind]
        d["unit"] = p.unit or k.canonical
        d["units"] = [{"unit": u, "label": units.label(u)} for u in k.units]
        d["unit_label"] = units.label(d["unit"])
    if p.columns:
        d["columns"] = []
        for c in p.columns:
            cd = asdict(c)
            if c.kind in units.KINDS:
                cd["unit"] = c.unit or units.KINDS[c.kind].canonical
                cd["units"] = [{"unit": u, "label": units.label(u)} for u in units.KINDS[c.kind].units]
            d["columns"].append(cd)
    return d


REGISTRY: dict[str, Calculator] = {}


def register(calc: Calculator) -> Calculator:
    if calc.id in REGISTRY:
        raise ValueError(f"duplicate calculator {calc.id}")
    REGISTRY[calc.id] = calc
    return calc


def _visible(p: Param, raw: dict[str, Any], resolved: dict[str, Any]) -> bool:
    if not p.show_if:
        return True
    for key, allowed in p.show_if.items():
        v = resolved.get(key, raw.get(key))
        if isinstance(v, dict):
            v = v.get("value")
        if v not in allowed:
            return False
    return True


def parse_inputs(calc: Calculator, raw: dict[str, Any]) -> dict[str, Any]:
    """Validate + convert raw API inputs to canonical values. Raises InputError with a field-specific message."""
    out: dict[str, Any] = {}
    for p in calc.all_inputs():
        if not _visible(p, raw, out):
            out[p.key] = None
            continue
        v = raw.get(p.key, p.default)
        if isinstance(v, dict) and p.kind in units.KINDS and v.get("value") in (None, ""):
            v = None
        if v is None or v == "":
            if p.optional or p.kind == "bool":
                out[p.key] = False if p.kind == "bool" else ("" if p.kind == "text" else None)
                continue
            raise InputError(f"{p.label} is required")
        out[p.key] = _convert(p, v)
    return out


def _convert(p: Param, v: Any) -> Any:
    """One raw (non-empty) input value → canonical value, or InputError."""
    if p.kind == "enum":
        vals = [o["value"] for o in p.options or []]
        if v not in vals:
            raise InputError(f"{p.label}: choose one of {', '.join(vals)}")
        return v
    elif p.kind == "bool":
        return bool(v)
    elif p.kind == "text":
        s = str(v).strip()
        if not s and not p.optional:
            if p.key == "sf_source":
                raise InputError("Safety factor source is required: say where the required factor comes from")
            raise InputError(f"{p.label} is required")
        return s[:300]
    elif p.kind == "table":
        if not isinstance(v, list) or not v:
            raise InputError(f"{p.label}: add at least one row")
        if len(v) > 50:
            raise InputError(f"{p.label}: at most 50 rows")
        rows = []
        for i, row in enumerate(v):
            if not isinstance(row, dict):
                raise InputError(f"{p.label} row {i + 1}: invalid")
            r: dict[str, Any] = {}
            for c in p.columns or []:
                cv = row.get(c.key, c.default)
                if c.kind == "text":
                    r[c.key] = str(cv or "")[:120]
                elif c.kind == "enum":
                    vals = [o["value"] for o in c.options or []]
                    if cv not in vals:
                        raise InputError(f"{p.label} row {i + 1}: {c.label} must be one of {', '.join(vals)}")
                    r[c.key] = cv
                else:
                    if cv is None or cv == "" or (isinstance(cv, dict) and cv.get("value") in (None, "")):
                        raise InputError(f"{p.label} row {i + 1}: {c.label} is required")
                    try:
                        x = units.quantity(c.kind, cv)
                    except units.UnitError as e:
                        raise InputError(f"{p.label} row {i + 1}, {c.label}: {e}") from e
                    except (TypeError, ValueError) as e:
                        raise InputError(f"{p.label} row {i + 1}: {c.label} must be a number") from e
                    if not math.isfinite(x):
                        raise InputError(f"{p.label} row {i + 1}: {c.label} must be finite")
                    if c.min is not None and x < c.min:
                        raise InputError(f"{p.label} row {i + 1}: {c.label} must be ≥ {c.min}")
                    r[c.key] = x
            rows.append(r)
        return rows
    else:
        try:
            x = units.quantity(p.kind, v)
        except units.UnitError as e:
            raise InputError(f"{p.label}: {e}") from e
        except (TypeError, ValueError) as e:
            raise InputError(f"{p.label} must be a number") from e
        if not math.isfinite(x):
            raise InputError(f"{p.label} must be a finite number")
        if p.min is not None and (x < p.min or (p.exclusive_min and x <= p.min)):
            raise InputError(f"{p.label} must be {'>' if p.exclusive_min else '≥'} {_fmt(p.min)} "
                             f"{units.KINDS[p.kind].label}".rstrip())
        if p.max is not None and x > p.max:
            raise InputError(f"{p.label} must be ≤ {_fmt(p.max)} {units.KINDS[p.kind].label}".rstrip())
        return x


def _fmt(x: float) -> str:
    return f"{x:g}"


def run(calc_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    calc = REGISTRY.get(calc_id)
    if calc is None:
        raise InputError(f"Unknown calculator '{calc_id}'")
    vals = parse_inputs(calc, raw)
    try:
        work = calc.func(vals)
    except ZeroDivisionError as e:
        raise InputError("These inputs give a division by zero; check the dimensions") from e
    except (ValueError, OverflowError) as e:
        if isinstance(e, InputError):
            raise
        raise InputError(str(e)) from e
    if calc.safety_factor:
        req, src = vals.get("sf_required"), (vals.get("sf_source") or "").strip()
        if req is not None and not src:
            raise InputError("Safety factor source is required: say where the required factor comes from")
        if work.sf_used and req is None:
            raise InputError("Enter the required safety factor and its source (design code, customer "
                             "specification or company standard)")
    return {
        "calc_id": calc.id, "calc_name": calc.name, "calc_version": calc.version, "engine": ENGINE_VERSION,
        "inputs": vals,
        "steps": [asdict(s) for s in work.steps],
        "outputs": [asdict(o) for o in work.outputs],
        "checks": [asdict(c) for c in work.checks],
        "warnings": work.warnings, "notes": work.notes,
        "references": calc.references, "assumptions": calc.assumptions,
        "verified_against": calc.verified_against,
        "level": "preliminary_estimate",
        "safety_factor": ({"required": vals.get("sf_required"), "source": vals.get("sf_source")}
                          if calc.safety_factor and vals.get("sf_required") is not None else None),
        "examples": example_inputs(calc, raw, vals),
    }


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12)
    return a == b


def example_inputs(calc: Calculator, raw: dict[str, Any], vals: dict[str, Any]) -> list[dict[str, str]]:
    """Load inputs still at the calculator's illustrative default (MAKE-19). Zero defaults ("no load") are not
    examples. Returns ``[{"key", "label"}]`` in schema order."""
    out = []
    for p in calc.inputs:
        if not _is_load(p) or p.default in (None, "", 0, 0.0) or vals.get(p.key) is None:
            continue
        try:
            dflt = _convert(p, p.default)
        except InputError:
            continue
        if p.kind == "table":
            nonzero = any(isinstance(x, (int, float)) and x for r in dflt for c, x in r.items()
                          if any(cc.key == c and cc.kind in LOAD_KINDS for cc in p.columns or []))
            if not nonzero:
                continue
        if _same(vals[p.key], dflt):
            out.append({"key": p.key, "label": p.label})
    return out


def output(result: dict[str, Any], key: str) -> Any:
    """Convenience for tests: canonical value of an output."""
    for o in result["outputs"]:
        if o["key"] == key:
            return o["value"]
    raise KeyError(key)


def sf(vals: dict[str, Any]) -> tuple[float | None, str]:
    return vals.get("sf_required"), vals.get("sf_source") or ""


def g(x: float, n: int = 4) -> str:
    """Engineering formatting for shown working: n significant figures, no scientific notation for normal ranges."""
    if x is None:
        return "—"
    if isinstance(x, str):
        return x
    if x == 0:
        return "0"
    ax = abs(x)
    if ax >= 1e7 or ax < 1e-4:
        return f"{x:.{n - 1}e}"
    digits = max(0, n - 1 - math.floor(math.log10(ax)))
    s = f"{x:.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s
