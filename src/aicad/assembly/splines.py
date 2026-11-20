"""Splined shaft / hub pairs in an assembly: placed by their interfaces and checked deterministically (ASM-OW).

A part's own checks (CHK-02..08) judge the part alone: they can't judge a fit with a partner that is not in the part's
view. The fit is judged here, where both parts are: the splines each build recorded (``fw.spline_shaft`` /
``fw.spline_bore`` feature records, snapshotted in the part's meta as ``splines``) are compared size for size, and
the placed pair is checked for being coaxial, inside the shaft's splined length and in phase (a hub groove on every
shaft tooth). Nominal sizes only: the fit class is a drawing callout, never claimed here.

Both helpers place a spline with its axis on the part's local Z through the origin and a tooth / groove on +X, so a
hub placed with the shaft's frame (shifted along Z) is in phase by construction.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from aicad.assembly import service, store, xform

TOL = 1e-6


def _g(x: float) -> str:
    return f"{round(float(x), 3):g}"


def of(root: Path, key: str, kind: str | None = None) -> list[dict[str, Any]]:
    """The splines of a part snapshot (external on a shaft, internal in a hub)."""
    p = store.part(root, key) or {}
    out = [s for s in p.get("splines") or [] if isinstance(s, dict)]
    return [s for s in out if kind is None or s.get("kind") == kind]


def pair(root: Path, doc: dict[str, Any], a: str, b: str) -> tuple[str, str, dict[str, Any], dict[str, Any]] | None:
    """(hub, shaft, internal spline, external spline) when one of the two instances is a splined hub and the other a
    splined shaft; else None."""
    for hub, shaft in ((a, b), (b, a)):
        ins = of(root, service._inst(doc, hub)["part"], "internal")
        ext = of(root, service._inst(doc, shaft)["part"], "external")
        if ins and ext:
            best = min(((i, e) for i in ins for e in ext), key=lambda ie: _mismatch(ie[0], ie[1]))
            return hub, shaft, best[0], best[1]
    return None


def _mismatch(i: dict[str, Any], e: dict[str, Any]) -> float:
    return abs(i["n"] - e["n"]) * 100 + abs(i["d"] - e["d"]) + abs(i["D"] - e["D"]) + abs(i["b"] - e["b"])


def spec_text(s: dict[str, Any]) -> str:
    return f"{s['n']} × {_g(s['d'])} × {_g(s['D'])} × {_g(s['b'])}"


def spec_problems(ins: dict[str, Any], ext: dict[str, Any]) -> list[str]:
    """What doesn't match between the hub's spline and the shaft's (nominal sizes)."""
    out = []
    if ins["n"] != ext["n"]:
        out.append(f"the hub has {ins['n']} splines, the shaft {ext['n']}")
    for k, what in (("d", "minor Ø"), ("D", "major Ø"), ("b", "spline width")):
        if abs(ins[k] - ext[k]) > TOL:
            out.append(f"{what}: hub {_g(ins[k])}, shaft {_g(ext[k])}")
    return out


def _faces(root: Path, key: str) -> dict[str, dict[str, Any]]:
    return store.refs(root, key).get("faces") or {}


def _axis_face(root: Path, key: str, r: float) -> int | None:
    for fid, f in sorted(_faces(root, key).items(), key=lambda kv: int(kv[0])):
        if f.get("kind") == "axis" and f.get("r") is not None and abs(float(f["r"]) - r) < 1e-4:
            v = np.asarray(f["v"], dtype=float)
            p = np.asarray(f["p"], dtype=float)
            if abs(abs(float(v[2])) - 1) < 1e-6 and math.hypot(float(p[0]), float(p[1])) < 1e-4:
                return int(fid)
    return None


def _plane_face(root: Path, key: str, z: float, nz: float, r_in: float) -> int | None:
    """A plane face at height z looking along nz whose extent reaches beyond radius r_in (a shoulder or an end
    face, not a tooth flank)."""
    for fid, f in sorted(_faces(root, key).items(), key=lambda kv: int(kv[0])):
        if f.get("kind") != "plane":
            continue
        v, p = np.asarray(f["v"], dtype=float), np.asarray(f["p"], dtype=float)
        if abs(float(v[2]) - nz) < 1e-6 and abs(float(p[2]) - z) < 1e-6:
            return int(fid)
    return None


def _flank(root: Path, key: str, b: float, ny: float) -> int | None:
    """The flank plane of the spline tooth / groove on +X: y = +b/2, normal ±Y."""
    for fid, f in sorted(_faces(root, key).items(), key=lambda kv: int(kv[0])):
        if f.get("kind") != "plane":
            continue
        v, p = np.asarray(f["v"], dtype=float), np.asarray(f["p"], dtype=float)
        if abs(float(v[1]) - ny) < 1e-6 and abs(float(p[1]) - b / 2) < 1e-6:
            return int(fid)
    return None


def place(root: Path, doc: dict[str, Any], hub: str, shaft: str, ins: dict[str, Any], ext: dict[str, Any]
          ) -> list[str]:
    """Put the hub on the shaft's spline by construction (its spline's top end at the shaft spline's top end, which
    is the shoulder for a seat against a collar), in phase, and mate it: concentric on the minor Ø, the flanks of
    the +X tooth together (no rotation), and the end face on the shoulder when the shaft has one there."""
    names = service.human_names(doc)
    Ts = xform.from12(service._inst(doc, shaft)["T"])
    shift = np.eye(4)
    shift[2, 3] = ext["z1"] - ins["z1"]
    service._inst(doc, hub)["T"] = xform.to12(Ts @ shift)
    kh, ks = service._inst(doc, hub)["part"], service._inst(doc, shaft)["part"]
    lines = [f"Fitz put {names[hub]} on the spline of {names[shaft]} ({spec_text(ext)}), in phase with its teeth"]
    ah, as_ = _axis_face(root, kh, ins["d"] / 2), _axis_face(root, ks, ext["d"] / 2)
    mates = []
    if ah is not None and as_ is not None:
        mates.append(("concentric", (shaft, as_), (hub, ah)))
    fs, fh = _flank(root, ks, ext["b"], 1.0), _flank(root, kh, ins["b"], -1.0)
    if fs is not None and fh is not None:
        mates.append(("coincident", (shaft, fs), (hub, fh)))
    sh = _plane_face(root, ks, ext["z1"], -1.0, ext["D"] / 2)
    hh = _plane_face(root, kh, ins["z1"], 1.0, ins["D"] / 2)
    if sh is not None and hh is not None:
        mates.append(("coincident", (shaft, sh), (hub, hh)))
        lines.append("Against the shoulder at the end of the spline")
    for typ, a, b in mates:
        service.make_mate(root, doc, {"type": typ, "a": {"inst": a[0], "kind": "face", "id": a[1]},
                                      "b": {"inst": b[0], "kind": "face", "id": b[1]}})
    if not mates:
        lines.append("I couldn't find the spline faces to mate: it is placed but not mated.")
    return lines


def check(root: Path, doc: dict[str, Any], hub: str, shaft: str, ins: dict[str, Any] | None = None,
          ext: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    """The spline fit, deterministic: sizes match, coaxial, the hub inside the shaft's splined length, in phase."""
    if ins is None or ext is None:
        pr = pair(root, doc, hub, shaft)
        if pr is None:
            return False, ["These two parts don't carry a matching pair of splines."]
        hub, shaft, ins, ext = pr
    names = service.human_names(doc)
    probs = spec_problems(ins, ext)
    Th, Ts = xform.from12(service._inst(doc, hub)["T"]), xform.from12(service._inst(doc, shaft)["T"])
    R = np.linalg.inv(Ts) @ Th              # the hub in the shaft's frame
    z_h = R[:3, 2]
    o = R[:3, 3]
    if abs(abs(float(z_h[2])) - 1) > 1e-6 or math.hypot(float(o[0]), float(o[1])) > 1e-3:
        probs.append("the hub is not on the shaft's axis")
    else:
        lo, hi = sorted((float(o[2] + z_h[2] * ins["z0"]), float(o[2] + z_h[2] * ins["z1"])))
        if lo < ext["z0"] - 1e-3 or hi > ext["z1"] + 1e-3:
            probs.append(f"the hub's spline ({_g(hi - lo)} long) runs off the shaft's splined length "
                         f"({_g(ext['z1'] - ext['z0'])} long)")
        x_h = R[:3, 0]
        ang = math.degrees(math.atan2(float(x_h[1]), float(x_h[0])))
        pitch = 360.0 / max(1, ext["n"])
        off = (ang % pitch + pitch) % pitch
        if min(off, pitch - off) > 0.01:
            probs.append(f"the hub's grooves are {_g(min(off, pitch - off))}° off the shaft's teeth")
    head = f"Spline fit {names[hub]} on {names[shaft]}"
    if probs:
        return False, [f"{head}: does not fit: " + "; ".join(probs)]
    return True, [(f"{head}: sizes match ({spec_text(ext)}, nominal), coaxial, inside the splined length, in phase "
                   "(the fit class is a drawing callout)")]


def check_all(root: Path, doc: dict[str, Any]) -> list[tuple[bool, str]]:
    """Every mated spline pair in the assembly."""
    seen, out = set(), []
    for m in doc["mates"]:
        a, b = m["a"]["inst"], m["b"]["inst"]
        k = tuple(sorted((a, b)))
        if k in seen:
            continue
        seen.add(k)
        try:
            pr = pair(root, doc, a, b)
        except Exception:  # noqa: BLE001, S112  (an instance without a snapshot: nothing to check)
            continue
        if pr:
            ok, lines = check(root, doc, *pr)
            out.append((ok, lines[0]))
    return out
