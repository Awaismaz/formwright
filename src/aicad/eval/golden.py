"""EVAL-003 / WORKLIST 46: the golden mechanism suite. Pure parts: cases, expectations, the results history.

A case is a brief plus hand-checked expectations, one TOML file in ``golden_cases/`` (formulas in its comments):

    id, title, letter, source, brief      what it is and where it came from
    fast = true                           one of the cases the pytest hook runs
    [sim] planner = "standard"            simulated runs: the office's own planner on the brief (no AI), or
    [sim] plan = "<file>.plan.json"       Archie's plan, replayed (a recorded or reference plan; no AI)
    [sim] intent = "<file>.intent.json"   a recorded intent reply, replayed when FW_DESIGN_GRAPH=1 (PD-110)
    [sim] master = "<file>.master.py"     a recorded master model, replayed when the office takes the master path
                                          (WORKLIST 50; ``FW_MASTER_MODEL=force`` forces that path for comparison)
    [limits] tokens, wall_simulated_s, wall_live_s
    [expect] complete, light, parts (part lines), pieces, subs, tickets, kinds = {kind = pieces}, no_extras,
             instances, clashes, binned, loose, placeholders, blocked, icd_problems, conformance, direct_min (parts
             built without AI: from the interfaces, or a designed part made from the Toolbox to the ICD),
             supervisor_max; only_simulated = [names]: counts that only a replayed plan fixes (a live planner may
             split or merge part lines); path = "master" | "fast": the layout path the office decided (WORKLIST 50)
    [[expect.at]] / span / along / distance / within / touch / same_span / count / stacks / reuse  (``CHECKS``)
    [[expect.planetary]] planets, ratio, centre_distance, rim_min_m, tol: a planetary set, checked on the plan's
             design graph (teeth, assembly condition, ratio, rim rule, mounting chain) and on the final assembly
             (planets equally spaced at a, gears coplanar, sun in the input shaft, carrier on the output, ring in the
             housing); one row per rule (``planetary_rows``)

Selectors pick final-assembly instances: ``{kind = "key"}`` (the head noun, ``office.scope.kind_of``) or
``{name = "regex"}``, optionally ``pick = "smallest" | "largest"`` (by box volume). Any geometric expectation may
carry ``modes = ["simulated"]`` when its numbers depend on sizes the replayed plan fixes (a live planner may choose
other sizes). Geometry is judged on world-axis boxes (each part's box placed by its instance transform), so "within"
and "touch" are box relations and "loose" means a box more than ``LOOSE_GAP_MM`` from every other box: a deliberately
lenient, deterministic proxy; Fitz's own measurements and the clash check stay the authority.

``axis = "auto"`` is the longest axis of the whole assembly's box (the shaft or rod axis of these mechanisms) and
``plane = "auto"`` the plane across it.

The history is an append-only JSONL file (``history_dir() / "runs.jsonl"``), one record per case run, stamped with
the git sha and the model routing in use. Nothing here touches the kernel, a model or the network.
"""

from __future__ import annotations

import json
import math
import os
import re
import tomllib
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "golden_cases"
SCHEMA = 1
LOOSE_GAP_MM = 0.5
AXES = {"x": 0, "y": 1, "z": 2}
COUNTS = ("parts", "pieces", "subs", "tickets", "instances", "clashes", "binned", "loose", "placeholders",
          "blocked", "icd_problems")
CHECKS = ("at", "span", "along", "distance", "within", "touch", "same_span", "count", "stacks", "reuse")
MULTI = ("planetary",)  # checks that give one row per rule they hold
LABELS = {
    "complete": "Program completes", "light": "Light path (one-step approval)", "parts": "Part lines planned",
    "pieces": "Pieces planned", "subs": "Sub-assemblies", "tickets": "Tickets", "kinds": "Kinds of part",
    "no_extras": "No extra kinds of part", "instances": "Instances in the final assembly",
    "clashes": "Clashes (whole-program check)", "binned": "Parts in the parts bin", "loose": "Loose parts",
    "placeholders": "Placeholders left", "blocked": "Tickets that stopped for the engineer",
    "icd_problems": "Interface problems at the gate", "conformance": "Parts conform to the interfaces",
    "direct_min": "Parts built without AI", "supervisor_max": "Supervisor interventions", "tokens": "Tokens",
    "path": "Layout path (fast or master model)",
    "wall": "Wall time",
}


class CaseError(ValueError):
    pass


# ----------------------------------------------------------------------------- cases
def load_case(path: Path) -> dict[str, Any]:
    try:
        case = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise CaseError(f"{path.name}: {e}") from e
    for k in ("id", "title", "brief"):
        if not isinstance(case.get(k), str) or not case[k].strip():
            raise CaseError(f"{path.name}: '{k}' is required")
    sim = case.setdefault("sim", {})
    if "plan" in sim:
        f = path.parent / str(sim["plan"])
        try:
            sim["plan_data"] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CaseError(f"{path.name}: plan {sim['plan']}: {e}") from e
    if "intent" in sim:
        f = path.parent / str(sim["intent"])
        try:
            sim["intent_data"] = json.loads(f.read_text(encoding="utf-8"))["reply"]
        except (OSError, ValueError, KeyError) as e:
            raise CaseError(f"{path.name}: intent {sim['intent']}: {e}") from e
    if "master" in sim:
        f = path.parent / str(sim["master"])
        try:
            sim["master_src"] = f.read_text(encoding="utf-8")
        except OSError as e:
            raise CaseError(f"{path.name}: master {sim['master']}: {e}") from e
    if "plan" not in sim and sim.get("planner", "standard") != "standard":
        raise CaseError(f"{path.name}: [sim] needs plan = <file> or planner = 'standard'")
    ex = case.setdefault("expect", {})
    unknown = set(ex) - set(COUNTS) - set(CHECKS) - set(MULTI) - {"complete", "light", "kinds", "no_extras", "conformance",
                                                     "direct_min", "supervisor_max", "only_simulated", "path"}
    if unknown:
        raise CaseError(f"{path.name}: unknown expectations {sorted(unknown)}")
    case.setdefault("limits", {})
    case["file"] = path.name
    return case


def load_cases(only: list[str] | None = None, folder: Path = CASES_DIR) -> list[dict[str, Any]]:
    cases = [load_case(p) for p in sorted(folder.glob("*.toml"))]
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise CaseError("duplicate case ids")
    if only:
        want = {o.strip() for o in only if o.strip()}
        stems = {c["file"].removesuffix(".toml") for c in cases}  # the file name works too ("k_planetary")
        missing = want - set(ids) - {c.get("letter") for c in cases} - stems
        if missing:
            raise CaseError(f"unknown case(s): {', '.join(sorted(missing))} (have {', '.join(ids)})")
        cases = [c for c in cases if c["id"] in want or c.get("letter") in want
                 or c["file"].removesuffix(".toml") in want]
    return cases


def applies(spec: dict[str, Any], mode: str, plan_fixed: bool | None = None) -> bool:
    """``modes = ["simulated"]`` means "only when the case's own plan is replayed" (its sizes fix the numbers)."""
    modes = spec.get("modes")
    if not modes:
        return True
    if "simulated" in modes and (plan_fixed if plan_fixed is not None else mode == "simulated"):
        return True
    return mode in modes and mode != "simulated"


# ----------------------------------------------------------------------------- geometry on world boxes
def world_box(T: list[float], bbox: list[float]) -> list[float]:
    """The axis-aligned box (x0, y0, z0, x1, y1, z1) of a part box placed by a row-major 4 x 4 transform."""
    x0, y0, z0, x1, y1, z1 = (float(v) for v in bbox)
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for x in (x0, x1):
        for y in (y0, y1):
            for z in (z0, z1):
                p = [T[0] * x + T[1] * y + T[2] * z + T[3], T[4] * x + T[5] * y + T[6] * z + T[7],
                     T[8] * x + T[9] * y + T[10] * z + T[11]]
                for k in range(3):
                    lo[k], hi[k] = min(lo[k], p[k]), max(hi[k], p[k])
    return [round(v, 6) + 0.0 for v in (*lo, *hi)]


def gap(a: list[float], b: list[float]) -> float:
    """Euclidean gap between two boxes (0 when they touch or overlap)."""
    d = [max(0.0, a[k] - b[k + 3], b[k] - a[k + 3]) for k in range(3)]
    return math.sqrt(sum(x * x for x in d))


def centre(b: list[float]) -> list[float]:
    return [(b[k] + b[k + 3]) / 2 for k in range(3)]


def hull(boxes: list[list[float]]) -> list[float]:
    return [min(b[k] for b in boxes) for k in range(3)] + [max(b[k + 3] for b in boxes) for k in range(3)]


def loose_names(insts: list[dict[str, Any]], tol: float = LOOSE_GAP_MM) -> list[str]:
    """Instances whose box is more than ``tol`` from every other instance's box (a lone part is never loose)."""
    if len(insts) < 2:
        return []
    return [a["name"] for a in insts if min(gap(a["box"], b["box"]) for b in insts if b is not a) > tol]


def _kind(name: str) -> str | None:
    from aicad.office import scope

    return scope.kind_of(re.sub(r"\s*[<(]\d+[>)]\s*$", "", name or ""))


def select(insts: list[dict[str, Any]], sel: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not sel:
        return []
    out = list(insts)
    if sel.get("kind"):
        out = [i for i in out if _kind(i["name"]) == sel["kind"]]
    if sel.get("name"):
        rx = re.compile(sel["name"])
        out = [i for i in out if rx.search(i["name"])]
    vol = lambda i: math.prod(max(0.0, i["box"][k + 3] - i["box"][k]) for k in range(3))
    if sel.get("pick") == "smallest" and out:
        out = [min(out, key=vol)]
    elif sel.get("pick") == "largest" and out:
        out = [max(out, key=vol)]
    return out


def _sel_text(sel: dict[str, Any] | None) -> str:
    if not sel:
        return "?"
    t = sel.get("kind") or re.sub(r"^\(\?i\)", "", sel.get("name", "?"))
    return f"{sel.get('pick')} {t}" if sel.get("pick") else t


def _axis(spec: dict[str, Any], insts: list[dict[str, Any]]) -> int:
    a = spec.get("axis", "auto")
    if a in AXES:
        return AXES[a]
    h = hull([i["box"] for i in insts]) if insts else [0, 0, 0, 0, 0, 0]
    ext = [h[k + 3] - h[k] for k in range(3)]
    return ext.index(max(ext))


def _r(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 3) + 0.0
    if isinstance(v, list):
        return [_r(x) for x in v]
    return v


def _row(eid: str, label: str, ok: bool | None, got: Any, want: Any, note: str = "") -> dict[str, Any]:
    return {"id": eid, "label": label, "ok": ok, "got": _r(got), "want": _r(want), **({"note": note} if note else {})}


def _geo(kind: str, n: int, spec: dict[str, Any], insts: list[dict[str, Any]],
         snap: dict[str, Any]) -> dict[str, Any]:
    eid = f"{kind}.{n}"
    tol = float(spec.get("tol", 0.01))
    if kind == "at":
        got = sorted(_r([i["T"][3], i["T"][7], i["T"][11]]) for i in select(insts, spec))
        want = sorted(_r([float(x) for x in p]) for p in spec["at"])
        ok = len(got) == len(want) and all(max(abs(a - b) for a, b in zip(g, w, strict=True)) <= tol
                                           for g, w in zip(got, want, strict=True))
        return _row(eid, f"{_sel_text(spec)} placed at", ok, got, want)
    if kind == "span":
        k = AXES[spec["axis"]]
        hit = select(insts, spec)
        if not hit:
            return _row(eid, f"{_sel_text(spec)} along {spec['axis'].upper()}", False, None, None, "not found")
        h = hull([i["box"] for i in hit])
        got = [h[k], h[k + 3]]
        want = [spec.get("min"), spec.get("max")]
        ok = all(w is None or abs(g - float(w)) <= tol for g, w in zip(got, want, strict=True))
        return _row(eid, f"{_sel_text(spec)} along {spec['axis'].upper()}", ok, got, want)
    if kind == "along":
        k = _axis(spec, insts)
        hit = select(insts, spec)
        label = f"{_sel_text(spec)} lies along {'XYZ'[k]}"
        if not hit:
            return _row(eid, label, False, None, "XYZ"[k], "not found")
        got = []
        for i in hit:
            ext = [i["box"][j + 3] - i["box"][j] for j in range(3)]
            got.append("XYZ"[ext.index(max(ext))])
        return _row(eid, label, all(g == "XYZ"[k] for g in got), got, "XYZ"[k])
    if kind == "distance":
        a = select(insts, spec["a"])
        b = select(insts, spec["b"]) if spec.get("b") else a[1:2]
        a = a[:1]
        label = f"{_sel_text(spec['a'])} to {_sel_text(spec.get('b') or spec['a'])}"
        if not a or not b:
            return _row(eid, label, False, None, spec["value"], "not found")
        ca, cb = centre(a[0]["box"]), centre(b[0]["box"])
        plane = spec.get("plane", "xyz")
        if plane == "auto":
            ax = _axis({"axis": "auto"}, insts)
            keep = [k for k in range(3) if k != ax]
        else:
            keep = [AXES[c] for c in plane]
        got = math.sqrt(sum((ca[k] - cb[k]) ** 2 for k in keep))
        return _row(eid, label, abs(got - float(spec["value"])) <= tol, got, float(spec["value"]))
    if kind in ("within", "same_span"):
        inner = select(insts, spec.get("inner") or spec.get("a"))
        outer = select(insts, spec.get("outer") or spec.get("b"))
        k = _axis(spec, insts)
        word = "inside" if kind == "within" else "same span as"
        label = f"{_sel_text(spec.get('inner') or spec.get('a'))} {word} {_sel_text(spec.get('outer') or spec.get('b'))}" \
                f" along {'XYZ'[k]}"
        if not inner or not outer:
            return _row(eid, label, False, len(inner), len(outer), "not found")
        boxes = [hull([o["box"] for o in outer])] if spec.get("hull") else [o["box"] for o in outer]
        spans = [[i["box"][k], i["box"][k + 3]] for i in inner]
        if kind == "within":
            ok = all(any(b[k] - tol <= s[0] and s[1] <= b[k + 3] + tol for b in boxes) for s in spans)
        else:
            ok = all(any(abs(b[k] - s[0]) <= tol and abs(b[k + 3] - s[1]) <= tol for b in boxes) for s in spans)
        return _row(eid, label, ok, spans, [[b[k], b[k + 3]] for b in boxes])
    if kind == "touch":
        a, b = select(insts, spec["a"]), select(insts, spec["b"])
        label = f"{_sel_text(spec['a'])} touches {_sel_text(spec['b'])}"
        if not a or not b:
            return _row(eid, label, False, None, 0, "not found")
        got = max(min(gap(x["box"], y["box"]) for y in b) for x in a)
        return _row(eid, label, got <= tol, got, 0.0)
    if kind == "count":
        got = len(select(insts, spec))
        return _row(eid, f"{_sel_text(spec)} placed", got == int(spec["n"]), got, int(spec["n"]))
    if kind == "stacks":
        got = sum(1 for s in snap.get("stacks") or [] if s.get("style") == spec["style"]
                  and float(s.get("size") or 0) == float(spec["size"]))
        return _row(eid, f"{spec['style']} M{spec['size']:g} fastener stacks", got == int(spec["n"]), got, int(spec["n"]))
    if kind == "reuse":
        t = next((t for t in snap.get("tickets") or [] if t.get("title") == spec["title"]), None)
        got = None if t is None else (t.get("reuse_code") or "")
        want = spec.get("code") or ""
        label = f"{spec['title']} from " + (f"Toolbox {want}" if want else "a designer, not the Toolbox")
        return _row(eid, label, got == want, got if got != "" else "designed", want or "designed",
                    "" if t else "no such ticket")
    raise CaseError(f"unknown check {kind}")


def planetary_rows(n: int, spec: dict[str, Any], insts: list[dict[str, Any]], snap: dict[str, Any]
                   ) -> list[dict[str, Any]]:
    """A single-stage planetary set, by hand rules (``[[expect.planetary]]``): on the plan's design graph
    (``snap["graph"]``) z_ring = z_sun + 2 z_planet, (z_sun + z_ring) / N whole, the ratio 1 + z_ring / z_sun (sun
    in, carrier out, ring fixed), the planet bearing's rim (root Ø - D) / 2 >= ``rim_min_m`` m, and the mounting
    chain (sun on the input shaft, carrier on the output shaft, ring fixed in the housing, each planet on its bearing
    on its pin in the carrier); on the final assembly's boxes the N planets equally spaced on a = m (z_s + z_p) / 2
    about the sun, every gear on one mid-plane, the sun inside the input shaft's span, the carrier inside the output
    shaft's span and the ring inside the housing."""
    from aicad.graph import planetary
    from aicad.graph.model import DesignGraph

    tol = float(spec.get("tol", 0.05))
    pre = f"planetary.{n}"
    rows: list[dict[str, Any]] = []
    data = snap.get("graph")
    ps = g = None
    if data:
        g = DesignGraph.model_validate(data)
        ps = planetary.find(g)
    if g is None or ps is None:
        return [_row(f"{pre}.set", "Planetary set in the design graph", False, None, "sun, planets, ring",
                     "no design graph" if g is None else "not read as a planetary set")]
    sun, pl, ring = g.comp(ps.sun), g.comp(ps.planet), g.comp(ps.ring)
    assert sun is not None and pl is not None and ring is not None
    zs, zp, zr = int(sun.v("teeth")), int(pl.v("teeth")), int(ring.v("teeth"))
    m = float(sun.v("module"))
    N = int(spec.get("planets") or ps.n)
    rows.append(_row(f"{pre}.coaxial", "z_ring = z_sun + 2 z_planet", zr == zs + 2 * zp, f"{zr} = {zs} + 2 x {zp}"
                     if zr == zs + 2 * zp else zr, zs + 2 * zp))
    rows.append(_row(f"{pre}.planets", "Planets", ps.n == N, ps.n, N))
    rows.append(_row(f"{pre}.assembly", "(z_sun + z_ring) / N whole", (zs + zr) % N == 0, (zs + zr) / N, "whole"))
    ratio = 1 + zr / zs
    if spec.get("ratio") is not None:
        rows.append(_row(f"{pre}.ratio", "Ratio 1 + z_ring / z_sun", abs(ratio - float(spec["ratio"])) <= 1e-6,
                         round(ratio, 4), float(spec["ratio"])))
    brg = g.comp(ps.bearing) if ps.bearing else None
    if spec.get("rim_min_m") is not None and brg is not None and brg.v("D") is not None:
        s_r = (m * (zp - 2.5) - float(brg.v("D"))) / 2
        rows.append(_row(f"{pre}.rim", "Planet rim (root Ø - bearing D) / 2", s_r >= float(spec["rim_min_m"]) * m - 1e-9,
                         f"{s_r:g} mm = {s_r / m:.3g} m ({brg.v('designation')})", f">= {spec['rim_min_m']} m"))

    def joined(kinds: tuple[str, ...], host: str | None, guest: str | None) -> bool:
        return any(x.kind in kinds and x.host == host and x.guest == guest for x in g.connections)

    hub = ("keyed_hub", "hub_fit")
    chain = {"sun on the input shaft": bool(ps.input) and joined(hub, ps.input, ps.sun),
             "carrier on the output shaft": bool(ps.output and ps.carrier) and joined(hub, ps.output, ps.carrier),
             "ring fixed in the housing": bool(ps.housing) and joined(("mounted_on", "bolted_joint"), ps.housing,
                                                                      ps.ring),
             "planet on its bearing on its pin": (joined(("mounted_on",), ps.bearing, ps.planet) and
                                                  joined(("bearing_journal",), ps.pin, ps.bearing)) if ps.bearing
             else joined(hub + ("mounted_on",), ps.pin, ps.planet),
             "pin in the carrier": bool(ps.carrier) and joined(("mounted_on", "shaft_bore"), ps.carrier, ps.pin)}
    bad = [k for k, ok in chain.items() if not ok]
    rows.append(_row(f"{pre}.chain", "Mounting chain", not bad, bad or "all", "sun in, carrier out, ring fixed"))
    # the final assembly
    a = float(spec.get("centre_distance") or m * (zs + zp) / 2)
    suns = select(insts, {"name": spec.get("sun", "(?i)\\bsun gear")})
    plans = select(insts, {"name": spec.get("planet", "(?i)\\bplanet gear")})
    rings = select(insts, {"name": spec.get("ring", "(?i)\\bring gear")})
    if not suns or len(plans) != N:
        rows.append(_row(f"{pre}.spacing", f"{N} planets equally spaced at a = {a:g}", False,
                         f"{len(suns)} sun, {len(plans)} planets", N, "not found"))
        return rows
    sb = suns[0]["box"]
    ext = [sb[k + 3] - sb[k] for k in range(3)]
    ax = ext.index(min(ext))  # the sun is a disc: its thin side is the axis
    keep = [k for k in range(3) if k != ax]
    cs = centre(sb)
    rad, ang = [], []
    for p in plans:
        cp = centre(p["box"])
        dx, dy = cp[keep[0]] - cs[keep[0]], cp[keep[1]] - cs[keep[1]]
        rad.append(round(math.hypot(dx, dy), 3))
        ang.append(math.degrees(math.atan2(dy, dx)) % 360)
    ang.sort()
    steps = [round((ang[(k + 1) % N] - ang[k]) % 360, 2) for k in range(N)]
    ok = all(abs(r - a) <= tol for r in rad) and all(abs(s_ - 360 / N) <= 0.5 for s_ in steps)
    rows.append(_row(f"{pre}.spacing", f"{N} planets equally spaced at a = {a:g}", ok,
                     {"radii": rad, "steps_deg": steps}, {"radius": a, "step_deg": round(360 / N, 2)}))
    gears = suns + plans + rings
    mids = [round((i["box"][ax] + i["box"][ax + 3]) / 2, 3) for i in gears]
    rows.append(_row(f"{pre}.coplanar", "Gears on one mid-plane", max(mids) - min(mids) <= tol,
                     sorted(set(mids)), "one plane"))

    def inside(inner: list[dict[str, Any]], outer: list[dict[str, Any]], only_axis: bool) -> bool:
        if not inner or not outer:
            return False
        ks = [ax] if only_axis else [0, 1, 2]
        return all(any(all(o["box"][k] - tol <= i["box"][k] and i["box"][k + 3] <= o["box"][k + 3] + tol for k in ks)
                       for o in outer) for i in inner)

    ins = select(insts, {"name": spec.get("input", "(?i)\\binput shaft")})
    outs = select(insts, {"name": spec.get("output", "(?i)\\boutput shaft")})
    cars = select(insts, {"name": spec.get("carrier", "(?i)carrier")})
    hss = select(insts, {"name": spec.get("housing", "(?i)housing base|gearbox base|\\bhousing\\b")})
    placed = {"sun within the input shaft's span": inside(suns, ins, True),
              "carrier within the output shaft's span": inside(cars, outs, True),
              "ring inside the housing": inside(rings, hss, False)}
    bad = [k for k, ok in placed.items() if not ok]
    rows.append(_row(f"{pre}.placed", "Sun on the input, carrier on the output, ring in the housing", not bad,
                     bad or "all", "all"))
    return rows


def evaluate(case: dict[str, Any], snap: dict[str, Any], mode: str, plan_fixed: bool | None = None
             ) -> list[dict[str, Any]]:
    """Every expectation of the case against a run snapshot (see ``golden_run.snapshot``). ``ok`` None = not
    measurable in this run (for example tokens in a simulated run). ``plan_fixed``: the case's own plan was replayed
    (default: simulated runs); a live planner or the design-graph path makes its own plan, so plan-specific numbers
    (``only_simulated`` counts, ``modes = ["simulated"]`` checks) don't apply."""
    fixed = (mode == "simulated") if plan_fixed is None else plan_fixed
    ex = case.get("expect") or {}
    lim = case.get("limits") or {}
    m = snap.get("metrics") or {}
    insts = snap.get("instances") or []
    rows: list[dict[str, Any]] = []
    if "complete" in ex:
        rows.append(_row("complete", LABELS["complete"], (snap.get("status") == "complete") == bool(ex["complete"]),
                         snap.get("status"), "complete" if ex["complete"] else "not complete",
                         snap.get("stopped") or ""))
    if "light" in ex:
        rows.append(_row("light", LABELS["light"], bool(m.get("light")) == bool(ex["light"]), bool(m.get("light")),
                         bool(ex["light"])))
    sim_only = set(ex.get("only_simulated") or []) if not fixed else set()
    for k in COUNTS:
        if k in ex and k not in CHECKS and k not in sim_only:
            got = m.get(k)
            rows.append(_row(k, LABELS[k], got is not None and int(got) == int(ex[k]), got, int(ex[k]),
                             "the whole-program check did not finish" if k == "clashes" and got is None else ""))
    kinds = snap.get("kinds") or {}
    if "kinds" in ex:
        want = {k: int(v) for k, v in ex["kinds"].items()}
        got = {k: int(kinds.get(k, 0)) for k in want}
        rows.append(_row("kinds", LABELS["kinds"], got == want, got, want))
    if ex.get("no_extras"):
        allowed = set((ex.get("kinds") or {}).keys())
        extra = {k: n for k, n in kinds.items() if k not in allowed and k != "none"}
        rows.append(_row("no_extras", LABELS["no_extras"], not extra, extra or "none", "none"))
    if "conformance" in ex:
        c = m.get("conformance") or {}
        ok = c.get("total", 0) == 0 or c.get("ok") == c.get("total")
        rows.append(_row("conformance", LABELS["conformance"], ok == bool(ex["conformance"]),
                         f"{c.get('ok', 0)} of {c.get('total', 0)} features", "all"))
    if "direct_min" in ex:
        n = int(m.get("no_ai", m.get("direct")) or 0)
        rows.append(_row("direct_min", LABELS["direct_min"], n >= int(ex["direct_min"]), n, f">= {ex['direct_min']}"))
    if "path" in ex and not (m.get("path_forced") and ex["path"] != m.get("path")):
        rows.append(_row("path", LABELS["path"], m.get("path") == ex["path"], m.get("path"), ex["path"],
                         m.get("path_words") or ""))
    if "supervisor_max" in ex:
        rows.append(_row("supervisor_max", LABELS["supervisor_max"],
                         int(m.get("supervisor") or 0) <= int(ex["supervisor_max"]), m.get("supervisor"),
                         f"<= {ex['supervisor_max']}"))
    for kind in CHECKS:
        for n, spec in enumerate(ex.get(kind) or [], start=1):
            if applies(spec, mode, fixed):
                try:
                    rows.append(_geo(kind, n, spec, insts, snap))
                except (KeyError, TypeError, ValueError, re.error) as e:
                    rows.append(_row(f"{kind}.{n}", kind, False, None, None, f"bad expectation: {e}"))
    for n, spec in enumerate(ex.get("planetary") or [], start=1):
        if applies(spec, mode, fixed):
            try:
                rows += planetary_rows(n, spec, insts, snap)
            except (KeyError, TypeError, ValueError, re.error) as e:
                rows.append(_row(f"planetary.{n}", "planetary set", False, None, None, f"bad expectation: {e}"))
    cap = lim.get("tokens")
    if cap is not None:
        live = mode == "live"
        rows.append(_row("tokens", LABELS["tokens"], (int(m.get("tokens") or 0) <= int(cap)) if live else None,
                         m.get("tokens"), f"<= {cap}", "" if live else "simulated metering, not spend"))
    wall = lim.get(f"wall_{mode}_s")
    if wall is not None:
        rows.append(_row("wall", LABELS["wall"], float(m.get("wall_s") or 0) <= float(wall), m.get("wall_s"),
                         f"<= {wall} s"))
    return rows


def passed(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(r["ok"] is not False for r in rows)


# ----------------------------------------------------------------------------- history (append-only JSONL)
def history_dir() -> Path:
    """``FW_GOLDEN_DIR``, else ``eval/golden/history`` in the repository (gitignored, outside ``data/``)."""
    env = os.environ.get("FW_GOLDEN_DIR", "").strip()
    if env:
        return Path(env)
    from aicad.platform.config import ROOT

    return ROOT / "eval" / "golden" / "history"


def append(record: dict[str, Any], folder: Path | None = None) -> Path:
    folder = folder or history_dir()
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "runs.jsonl"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return f


def read(folder: Path | None = None, limit: int = 5000) -> list[dict[str, Any]]:
    f = (folder or history_dir()) / "runs.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("schema") == SCHEMA and r.get("case"):
            out.append(r)
    return out


def routing_id(routes: dict[str, str]) -> str:
    """A short, stable fingerprint of the model routing (the dashboard shows this, never model names)."""
    import hashlib

    return hashlib.sha1(json.dumps(routes, sort_keys=True).encode()).hexdigest()[:6]


def public(record: dict[str, Any]) -> dict[str, Any]:
    """A history record as the admin dashboard may show it: numbers and plain labels, no model names or internals."""
    keep = ("run_id", "suite_id", "at", "sha", "dirty", "mode", "case", "title", "letter", "passed", "status",
            "stopped", "metrics", "expectations", "routing_id", "error", "flags")
    return {k: record.get(k) for k in keep}


def gather_routing() -> dict[str, str]:
    from aicad.llm import routing

    return {k: routing.tier_of(None if v.endswith("(default)") else v) for k, v in routing.describe().items()}


def git_stamp(root: Path | None = None) -> tuple[str, bool]:
    import subprocess

    if root is None:
        from aicad.platform.config import ROOT as root
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=10", "HEAD"], cwd=root, capture_output=True, text=True, check=False,
                             timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                                    capture_output=True, text=True, timeout=10, check=False).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return "unknown", False
    return sha or "unknown", dirty
