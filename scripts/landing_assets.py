"""Regenerate the landing page's 3D parts (web/public/landing/**.glb) from real Formwright geometry.

Run from the repo root:  unset VIRTUAL_ENV && uv run python scripts/landing_assets.py
GLB is in metres, Y up (build123d export); the landing viewer scales back to millimetres.

Two sets:
* the Toolbox tour parts (flange, gear, bearing, fasteners) used by the scroll sections;
* the hero's planetary gearbox PG-5 (web/public/landing/gearbox/), one GLB per unique part plus a manifest
  (web/src/components/landing/hero/gearbox.json) that places every instance in assembly coordinates (mm, Z = gearbox
  axis, motor side at -Z). Gears, bearings, screws and dowels come from the Toolbox; the internal ring gear, carrier,
  shafts, pins and housing are build123d parts made here.

Gear set (ring fixed, sun input, carrier output): m 1.5, sun 18T, 3 planets 27T, ring 72T internal, face width 12.
  ratio i = 1 + Zr/Zs = 1 + 72/18 = 5;  ring check Zs + 2 Zp = 18 + 54 = 72;  assembly (Zs + Zr)/N = 90/3 = 30 (integer);
  centre distance a = m (Zs + Zp)/2 = 1.5 * 45 / 2 = 33.75 mm (carrier pin PCD 67.5).
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np
from build123d import Box, Polygon, Pos, RectangleRounded, Rot, chamfer, export_gltf, extrude

from aicad import toolbox
from aicad.toolbox import _cyl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "public" / "landing"
GBX = OUT / "gearbox"
MANIFEST = ROOT / "web" / "src" / "components" / "landing" / "hero" / "gearbox.json"
FLANGE = {"OD": 150, "T": 16, "BORE": 60, "N": 6, "HOLE": 14, "PCD": 120}

# ---------------------------------------------------------------- gearbox design values (mm)
M, ZS, ZP, ZR, N, FW = 1.5, 18, 27, 72, 3, 12.0
A = M * (ZS + ZP) / 2  # 33.75 centre distance
assert ZR == ZS + 2 * ZP and (ZS + ZR) % N == 0
RING_OD, RING_PCD, CASE_D = 132.0, 122.0, 132.0
PLATE_D = 86.0
NEMA23_SQ, NEMA23_PILOT = 47.14, 38.1
SCREW_ANG = [0, 60, 120, 180, 240, 300]
DOWEL_ANG = [30, 210]
PIN_ANG = [0, 120, 240]
POST_ANG = [60, 180, 300]


def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * np.array(node.get("scale", [1, 1, 1]))
    m[:3, 3] = node.get("translation", [0, 0, 0])
    return m


def compact_glb(path: Path, smooth_deg: float = 32.0) -> None:
    """Rewrite a build123d GLB (one primitive per B-rep face, so hundreds of draw calls) as ONE indexed primitive.

    Node transforms are baked in, UVs dropped, and normals are averaged across facets that meet at less than
    `smooth_deg` (involute flanks and cylinders shade smoothly, real edges stay sharp). Geometry is unchanged."""
    raw = path.read_bytes()
    jlen = struct.unpack("<I", raw[12:16])[0]
    gj = json.loads(raw[20:20 + jlen])
    bin_ = raw[20 + jlen + 8:]
    ctype = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}

    def acc(i: int) -> np.ndarray:
        a = gj["accessors"][i]
        bv = gj["bufferViews"][a["bufferView"]]
        dt = np.dtype(ctype[a["componentType"]])
        k = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[a["type"]]
        stride = bv.get("byteStride", dt.itemsize * k)
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        rows = np.lib.stride_tricks.as_strided(np.frombuffer(bin_, dtype=np.uint8, offset=start),
                                               shape=(a["count"], dt.itemsize * k), strides=(stride, 1))
        return np.ascontiguousarray(rows).view(dt).reshape(a["count"], k)

    pos, nrm, idx = [], [], []
    base = 0

    def walk(n: int, parent: np.ndarray) -> None:
        nonlocal base
        node = gj["nodes"][n]
        m = parent @ _node_matrix(node)
        if "mesh" in node:
            for p in gj["meshes"][node["mesh"]]["primitives"]:
                v = acc(p["attributes"]["POSITION"]).astype(float)
                nn = acc(p["attributes"]["NORMAL"]).astype(float)
                ii = acc(p["indices"]).reshape(-1).astype(np.int64)
                pos.append(v @ m[:3, :3].T + m[:3, 3])
                nn = nn @ m[:3, :3].T
                nrm.append(nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12))
                idx.append(ii + base)
                base += len(v)
        for c in node.get("children", []):
            walk(c, m)

    for r in gj["scenes"][gj.get("scene", 0)]["nodes"]:
        walk(r, np.eye(4))
    P, Nn, I = np.vstack(pos), np.vstack(nrm), np.concatenate(idx)
    # crease-aware smoothing: average normals of coincident vertices whose normals are within smooth_deg
    key = np.round(P / 1e-6).astype(np.int64)
    _, inv, counts = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    order = np.argsort(inv, kind="stable")
    bounds = np.concatenate([[0], np.cumsum(counts)])
    cosmax = math.cos(math.radians(smooth_deg))
    out = Nn.copy()
    for g in np.nonzero(counts > 1)[0]:
        members = order[bounds[g]:bounds[g + 1]]
        nm = Nn[members]
        s = (nm @ nm.T > cosmax).astype(float) @ nm
        out[members] = s / np.maximum(np.linalg.norm(s, axis=1, keepdims=True), 1e-12)
    # weld vertices that now share position and normal
    vk = np.hstack([key, np.round(out * 1e4).astype(np.int64)])
    _, first, remap = np.unique(vk, axis=0, return_index=True, return_inverse=True)
    P, out, I = P[first].astype(np.float32), out[first].astype(np.float32), remap.reshape(-1)[I]
    it = np.uint16 if len(P) < 65536 else np.uint32
    ib = I.astype(it).tobytes()
    ib += b"\0" * (-len(ib) % 4)
    pb, nb = P.tobytes(), out.tobytes()
    blob = pb + nb + ib
    doc = {
        "asset": {"version": "2.0", "generator": "Formwright landing_assets"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": path.stem}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "mode": 4}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pb), "target": 34962},
                        {"buffer": 0, "byteOffset": len(pb), "byteLength": len(nb), "target": 34962},
                        {"buffer": 0, "byteOffset": len(pb) + len(nb), "byteLength": len(I) * np.dtype(it).itemsize,
                         "target": 34963}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(P), "type": "VEC3",
             "min": P.min(0).tolist(), "max": P.max(0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": len(P), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123 if it is np.uint16 else 5125, "count": len(I), "type": "SCALAR"},
        ],
    }
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def save(name: str, shape: object, lin: float = 0.05, ang: float = 0.25, folder: Path = OUT) -> int:
    path = folder / f"{name}.glb"
    export_gltf(shape, str(path), binary=True, linear_deflection=lin, angular_deflection=ang)
    compact_glb(path)
    size = path.stat().st_size
    print(f"{path.relative_to(OUT).as_posix():28s} {size / 1024:7.1f} KB")
    return size


def involute_outline(m: float, z: int, r_tip: float, r_root: float, flank: int = 8, land: int = 3,
                     backlash: float = 0.0) -> list[tuple[float, float]]:
    """Closed outline of an external involute gear (alpha 20 deg) with explicit tip/root radii; tooth 0 centred on +X.

    Used for the ring gear: an internal gear's tooth SPACE is the tooth of an external gear with the same module,
    tooth count and base circle, so the ring is a disc minus this outline with r_tip = rp + 1.25 m (ring root) and
    r_root = rp - m (ring tip). `backlash` (mm, at any radius) widens each tooth, i.e. each ring space."""
    alpha = math.radians(20)
    rp = m * z / 2
    rb = rp * math.cos(alpha)

    def inv(x: float) -> float:
        return math.tan(x) - x

    def psi(r: float) -> float:
        r = max(r, rb)
        return math.pi / (2 * z) + inv(alpha) - inv(math.acos(rb / r)) + backlash / (2 * r)

    r0 = max(rb, r_root)
    radii = [r0 + (r_tip - r0) * (i / flank) for i in range(flank + 1)]
    pts: list[tuple[float, float]] = []
    for i in range(z):
        phi = 2 * math.pi * i / z
        pts += [(r * math.cos(phi - psi(r)), r * math.sin(phi - psi(r))) for r in radii]
        pts += [(r * math.cos(phi + psi(r)), r * math.sin(phi + psi(r))) for r in reversed(radii)]
        a0, a1 = phi + psi(r0), phi + 2 * math.pi / z - psi(r0)
        pts += [(r_root * math.cos(a0 + (a1 - a0) * j / (land + 1)), r_root * math.sin(a0 + (a1 - a0) * j / (land + 1)))
                for j in range(1, land + 1)]
    return [(round(x, 5), round(y, 5)) for x, y in pts]


def polar(r: float, deg: float) -> tuple[float, float]:
    return r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg))


def holes(part: Any, r: float, d: float, angles: list[float], z0: float, h: float) -> Any:
    for a in angles:
        x, y = polar(r, a)
        part -= Pos(x, y, 0) * _cyl(d / 2, h + 0.02, z0 - 0.01)
    return part


def circle_edges(part: Any, r: float | None = None, z: float | None = None) -> Any:
    def ok(e: Any) -> bool:
        if e.geom_type.name != "CIRCLE":
            return False
        return (r is None or abs(e.radius - r) < 1e-3) and (z is None or abs(e.center().Z - z) < 1e-3)

    return part.edges().filter_by(ok)


def ring_gear() -> Any:
    rp = M * ZR / 2
    space = extrude(Polygon(*involute_outline(M, ZR, rp + 1.25 * M, rp - M, backlash=0.08), align=None), FW + 0.02)
    ring = _cyl(RING_OD / 2, FW) - Pos(0, 0, -0.01) * space
    ring = holes(ring, RING_PCD / 2, 5.5, SCREW_ANG, 0, FW)
    return holes(ring, RING_PCD / 2, 5.0, DOWEL_ANG, 0, FW)


def carrier_plate_a() -> Any:
    """Input-side plate z -6..-2 with three Ø12 posts between the planets (to z 14), pin holes on PCD 2a."""
    p = _cyl(PLATE_D / 2, 4, -6) - _cyl(9, 4.2, -6.1)
    for a in POST_ANG:
        x, y = polar(A, a)
        p += Pos(x, y, 0) * _cyl(6, 16, -2)
        p -= Pos(x, y, 0) * _cyl(2.1, 10, 4.1)  # M5 tap drill for the plate B screws
    p = holes(p, A, 10, PIN_ANG, -6, 4)
    return chamfer(circle_edges(p, PLATE_D / 2), 0.8)


def carrier_plate_b() -> Any:
    p = _cyl(PLATE_D / 2, 4, 14) - _cyl(10, 4.2, 13.9)
    p = holes(p, A, 10, PIN_ANG, 14, 4)
    p = holes(p, A, 5.5, POST_ANG, 14, 4)
    return chamfer(circle_edges(p, PLATE_D / 2), 0.8)


def planet_pin() -> Any:
    return chamfer(_cyl(5, 24, -6).edges(), 0.6)


def input_shaft() -> Any:
    """Ø12 shaft z -22..12, Ø16 shoulder z -4..0 under the sun, Ø6.35 socket for the NEMA 23 motor shaft."""
    s = _cyl(6, 34, -22) + _cyl(8, 4, -4)
    s -= _cyl(6.35 / 2, 16, -22.01)
    s -= Pos(0, 0, -15) * Rot(0, 90, 0) * _cyl(1.5, 7, 0)  # M3 set screw onto the motor shaft flat
    return chamfer(circle_edges(s, 6, 12), 0.6)


def output_shaft() -> Any:
    """Ø20 z 14..56 through carrier plate B and the two 6204s, Ø24 shoulder z 18..22, Ø16 output z 56..84 with keyway."""
    s = _cyl(10, 42, 14) + _cyl(12, 4, 18) + _cyl(8, 28, 56)
    s -= Pos(0, 8 - 3 + 2.5, 72) * Box(5, 5, 20)  # DIN 6885 key 5 x 5, shaft groove t1 = 3, length 20
    return chamfer(circle_edges(s, 8, 84), 0.8)


def input_cover() -> Any:
    """Motor-side housing half z -18..0: Ø92 carrier pocket, 6001 bearing seat, tapped M5 holes and dowel holes."""
    c = _cyl(CASE_D / 2, 18, -18)
    c -= _cyl(46, 8.01, -8)
    c -= _cyl(14, 8, -16)  # 6001 seat (D 28)
    c -= _cyl(8, 2.02, -18.01)
    c = holes(c, RING_PCD / 2, 5.0, SCREW_ANG, -16, 16)  # M5 tapped, thread cosmetic at nominal Ø (Toolbox rule)
    c = holes(c, RING_PCD / 2, 5.0, DOWEL_ANG, -8, 8)
    for a in range(0, 360, 60):  # weight-relief scallops on the motor face
        x, y = polar(30, a + 30)
        c -= Pos(x, y, 0) * _cyl(7, 3, -18.01)
    return chamfer(circle_edges(c, CASE_D / 2, -18), 1.5)


def output_cover() -> Any:
    """Output housing half: 140 square mounting flange z 12..20 (4 × Ø9), bearing boss Ø64 to z 56 for 2 × 6204."""
    c = Pos(0, 0, 12) * extrude(RectangleRounded(140, 140, 12), 8) + _cyl(32, 36, 20)
    for a in range(45, 360, 90):  # four stiffening ribs from flange to boss
        c += Pos(0, 0, 28) * Rot(0, 0, a) * Pos(44, 0, 0) * Box(24, 5, 16)
    c -= _cyl(46, 7.01, 11.99)  # carrier pocket
    c -= _cyl(15, 3.02, 18.99)  # shoulder bore
    c -= _cyl(23.5, 32, 22)  # 6204 seats (D 47)
    c -= _cyl(13, 2.02, 53.99)  # seal bore
    c = holes(c, RING_PCD / 2, 5.5, SCREW_ANG, 12, 8)
    c = holes(c, RING_PCD / 2, 5.0, DOWEL_ANG, 12, 4)
    for sx in (-1, 1):
        for sy in (-1, 1):
            c -= Pos(sx * 58, sy * 58, 0) * _cyl(4.5, 8.02, 11.99)
    return c


def motor_flange() -> Any:
    """NEMA 23 adapter z -26..-18: 76 square, Ø38.1 pilot recess, 4 × Ø5.5 on the 47.14 square, Ø22 clearance."""
    f = Pos(0, 0, -26) * extrude(RectangleRounded(76, 76, 8), 8)
    f -= _cyl(NEMA23_PILOT / 2, 2.01, -26.01)
    f -= _cyl(11, 8.02, -26.01)
    for sx in (-1, 1):
        for sy in (-1, 1):
            f -= Pos(sx * NEMA23_SQ / 2, sy * NEMA23_SQ / 2, 0) * _cyl(2.75, 8.02, -26.01)
    return f


def gearbox() -> None:
    GBX.mkdir(parents=True, exist_ok=True)
    tb = toolbox.build
    unique: dict[str, Any] = {
        # Axel (gears): sun and planet are the Toolbox spur gear; the ring is the internal involute above
        "sun": tb("spur_gear", M=M, Z=ZS, B=FW, BORE=12)[0],
        "planet": tb("spur_gear", M=M, Z=ZP, B=FW, BORE=26)[0],
        "ring": ring_gear(),
        # Chuck (turned)
        "input_shaft": input_shaft(),
        "output_shaft": output_shaft(),
        "pin": planet_pin(),
        # Mill (machined)
        "carrier_a": carrier_plate_a(),
        "carrier_b": carrier_plate_b(),
        "input_cover": input_cover(),
        "output_cover": output_cover(),
        "motor_flange": motor_flange(),
        # Hex (Toolbox standard parts)
        "b6204": tb("bearing", SERIES=6204)[0],
        "b6001": tb("bearing", SERIES=6001)[0],
        "b6000": tb("bearing", SERIES=6000)[0],
        "shcs_m5": tb("shcs", D=5, L=35)[0],
        "dowel": tb("dowel", D=5, L=16)[0],
    }
    sizes = {k: save(k, s, 0.08, 0.5, folder=GBX) for k, s in unique.items()}

    def at(x: float = 0, y: float = 0, z: float = 0) -> list[float]:
        return [round(x, 4), round(y, 4), round(z, 4)]

    inst: list[dict[str, Any]] = []

    def add(part: str, pos: list[float], move: str, n: int | None = None) -> None:
        inst.append({"id": f"{part}{'' if n is None else n}", "part": part, "at": pos, "move": move})

    add("motor_flange", at(), "fixed")
    add("input_cover", at(), "fixed")
    add("b6001", at(z=-16), "fixed")
    add("input_shaft", at(), "sun")
    add("carrier_a", at(), "carrier")
    for k, a in enumerate(PIN_ANG):
        add("pin", at(*polar(A, a)), "carrier", n=k)
        add("b6000", at(*polar(A, a), 2), "planet", n=k)
        add("planet", at(*polar(A, a)), "planet", n=k)
    add("sun", at(), "sun")
    add("ring", at(), "fixed")
    for k, a in enumerate(DOWEL_ANG):
        add("dowel", at(*polar(RING_PCD / 2, a), -8), "fixed", n=k)
    add("carrier_b", at(), "carrier")
    add("output_shaft", at(), "carrier")
    add("b6204", at(z=24), "fixed", n=0)
    add("b6204", at(z=40), "fixed", n=1)
    add("output_cover", at(), "fixed")
    for k, a in enumerate(SCREW_ANG):
        add("shcs_m5", at(*polar(RING_PCD / 2, a), 20), "fixed", n=k)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "note": "Generated by scripts/landing_assets.py. Units mm, Z = gearbox axis. Do not edit by hand.",
        "gear": {"m": M, "zs": ZS, "zp": ZP, "zr": ZR, "n": N, "a": A, "faceWidth": FW},
        "planetAngles": PIN_ANG,
        "bytes": sizes,
        "instances": inst,
    }, indent=1) + "\n")
    print(f"gearbox total {sum(sizes.values()) / 1024:.1f} KB, {len(inst)} instances")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save("flange", toolbox.build("flange", **FLANGE)[0])
    # Toolbox carousel, recognition and the bolted-joint assembly
    save("gear", toolbox.build("spur_gear", M=2, Z=24, B=12, BORE=10)[0], 0.2, 0.6)
    save("bearing", toolbox.build("bearing", SERIES=6204)[0], 0.1, 0.6)
    save("hex_bolt", toolbox.build("hex_bolt", D=12, L=55)[0])
    save("hex_nut", toolbox.build("hex_nut", D=12)[0])
    save("washer", toolbox.build("washer", D=12)[0])
    save("shcs", toolbox.build("shcs", D=8, L=30)[0])
    gearbox()


if __name__ == "__main__":
    main()
