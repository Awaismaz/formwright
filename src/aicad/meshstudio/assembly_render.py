"""Render an assembly from Assembly Studio (AMI-I4): every visible instance placed as in the assembly (optionally
exploded), each part in the finish its material suggests, one Blender scene.

Read-only on the assembly: the document and the org's part cache (`aicad.assembly.store`) are only read. Renders
live in their own folder, `<data>/meshstudio/assemblies/<org>/<assembly>/mesh/`, laid out like a project's, so the
queue, cache, gallery and file serving are the project ones. Each instance's cached `part.step` is tessellated once
per file content into a geometry cache shared by the org's assemblies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from aicad.assembly import service as asm
from aicad.assembly import store, xform
from aicad.meshstudio import VERSION, geometry, presets, runner, scene, service

EXPLODE_STEPS = (0.0, 0.25, 0.5, 0.75, 1.0)


def workspace(data_dir: Path, org_id: str, aid: str) -> Path:
    """The render folder of one assembly (ids are validated by the assembly store)."""
    store.doc_dir(store.org_root(data_dir, org_id), aid)  # raises on a malformed id
    ws = data_dir / "meshstudio" / "assemblies" / org_id / aid
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def signature(doc: dict[str, Any]) -> int:
    """A number that changes when the placed geometry changes (parts, placements, visibility): the assembly's
    'build' for the stale-render flag. Written where the gallery looks for the current build."""
    sig = asm.geometry_signature({"instances": [i for i in doc["instances"] if i.get("visible", True)]})
    return int(sig[:12], 16)


def _stamp(ws: Path, doc: dict[str, Any]) -> int:
    bid = signature(doc)
    (ws / "out").mkdir(parents=True, exist_ok=True)
    (ws / "out" / "status.json").write_text(json.dumps({"build_id": bid, "ok": True}), encoding="utf-8")
    return bid


def _geom_root(ws: Path) -> Path:
    return ws.parent / "_geom"


def parts(root: Path, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The distinct parts of the assembly with their count and suggested finish (from the part's material)."""
    names = asm.display_names(doc)
    out: dict[str, dict[str, Any]] = {}
    for i in doc["instances"]:
        p = store.part(root, i["part"])
        if p is None:
            raise ValueError("A part snapshot of this assembly is missing. Open it in Assembly Studio first.")
        row = out.get(i["part"])
        if row is None:
            sug = presets.map_material(p.get("material"))
            base = names[i["id"]].rsplit("<", 1)[0]
            row = out[i["part"]] = {"key": i["part"], "name": base, "material": p.get("material"),
                                    "finish": sug["finish"], "colour": sug["colour"], "count": 0, "visible": 0}
        row["count"] += 1
        row["visible"] += 1 if i.get("visible", True) else 0
    return list(out.values())


def items(root: Path, ws: Path, doc: dict[str, Any], explode: float) -> tuple[list[dict[str, Any]], list[Path], int]:
    """Placed visible instances for the scene, the mesh files (one per distinct part) and the triangle total."""
    names = asm.display_names(doc)
    offsets = asm.explode(root, doc) if explode > 0 else {}
    finishes = {p["key"]: p for p in parts(root, doc)}
    meshes: list[Path] = []
    index: dict[str, int] = {}
    hulls: dict[str, np.ndarray] = {}
    tris: dict[str, int] = {}
    out = []
    for i in doc["instances"]:
        if not i.get("visible", True):
            continue
        key = i["part"]
        if key not in index:
            g = geometry.build_geometry(store.part_dir(root, key) / "part.step", _geom_root(ws))
            npz = _geom_root(ws) / g["file"]
            index[key] = len(meshes)
            meshes.append(npz)
            hulls[key] = geometry.hull_points(npz, np.eye(3), np.zeros(3)) * 1000.0
            tris[key] = g["triangles"]
        T = xform.from12(i["T"])
        T[:3, 3] += np.asarray(offsets.get(i["id"], [0.0, 0.0, 0.0])) * explode
        f = finishes[key]
        out.append({"name": names[i["id"]], "hull_mm": hulls[key], "T": T, "geom": index[key],
                    "finish": f["finish"], "colour": f["colour"]})
    if not out:
        raise ValueError("Every part of this assembly is hidden. Show at least one part to render it.")
    return out, meshes, sum(tris[i["part"]] for i in doc["instances"] if i.get("visible", True))


def info(ws: Path, root: Path, doc: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Everything the Mesh Studio page needs for an assembly, in the same shape as a project's."""
    bid = _stamp(ws, doc)
    ps = parts(root, doc)
    return {"kind": "assembly",
            "project": {"id": doc["id"], "name": doc["name"], "material": None, "build_id": bid, "revision": None},
            "suggested": {"finish": "clay", "colour": None, "matched": None}, "look": None,
            "parts": ps, "instances": sum(p["visible"] for p in ps), "explode_steps": list(EXPLODE_STEPS),
            "mesh": None, **service.list_jobs(ws, base_url)}


def request(ws: Path, root: Path, doc: dict[str, Any], opts: scene.Options, explode: float, org_id: str,
            user_id: str, base_url: str = "") -> dict[str, Any]:
    """Queue an assembly render (or return the cached / in-flight one for the same geometry, look and explode)."""
    opts.validate()
    if not 0.0 <= explode <= 1.0:
        raise ValueError("Explode must be between 0 and 100 %.")
    dev = runner.detect()
    if not dev.get("available"):
        raise runner.BlenderError("Rendering isn't available on this server (Blender is not installed).")
    if not any(i.get("visible", True) for i in doc["instances"]):
        raise ValueError("Every part of this assembly is hidden. Show at least one part to render it.")
    bid = _stamp(ws, doc)
    kind = "turntable" if presets.is_turntable(opts.quality) else opts.quality
    look = {k: v for k, v in opts.key().items() if k != "finish" and k != "colour"}  # finishes come per part
    key = scene.spec_hash({"v": VERSION, "asm": bid, "parts": [p["key"] for p in parts(root, doc)], "opts": look,
                           "explode": round(explode, 3), "dev": dev["device"]})[:16]
    label = (f"Assembly · {presets.LIGHTING[opts.lighting]['label']} · {presets.CAMERAS[opts.camera]['label']}"
             + (f" · exploded {round(explode * 100)} %" if explode > 0 else ""))
    name = doc["name"]

    def stage(outputs: dict[str, Any]) -> tuple[dict[str, Any], list[Path], int, dict[str, Any]]:
        its, meshes, tri = items(root, ws, doc, explode)
        spec = scene.build_assembly_spec(its, opts, dev, name, outputs)
        meta = {"Title": f"{name} (visualisation render of an assembly)", "Formwright-Finish": "per part, from its material",
                "Formwright-Mesh": f"{tri} triangles"}
        return spec, meshes, tri, meta

    return service._enqueue(ws, kind, key, {"options": {**opts.key(), "explode": explode}, "label": label,
                                            "explode": explode}, org_id, user_id, base_url,
                            lambda d, j: service._execute_render(ws, d, j, name, opts, dev, stage))
