"""CAD-070: "Export for SOLIDWORKS" - a STEP pathway with explicit disclosure (no native feature history).

What the package holds (one zip):

* ``<Part>.step`` - the project's verified solid, re-written for SOLIDWORKS import: AP214 (default) or AP242,
  millimetres (``SI_UNIT(.MILLI.,.METRE.)``), the product and body named after the part (so the FeatureManager shows
  the part name, not "Part1" / "Imported1"), and a body colour when the material maps to one (``meshstudio.presets``).
  The written file is read back and compared with the verified build (volume, bounding-box corners, solid count);
  a mismatch refuses the export instead of shipping a wrong file.
* ``<Part>_parameters.csv`` - the model's declared parameters (name, value, unit, editable, limits) so the design
  intent travels as data next to the dumb solid.
* ``README_SOLIDWORKS.txt`` - the disclosure: SOLIDWORKS imports a **dumb solid (an "Imported" feature) with no
  Formwright feature history**; parameters do not drive it; how to re-run a change (edit in Formwright, re-export);
  where native feature trees are planned (Native CAD bridge, ``docs/plans/NATIVE_CAD_BRIDGE.md``). It does **not**
  claim the file was opened in SOLIDWORKS: that is the founder's periodic manual check (EVAL-005).

No CAD claim beyond what is checked here; never "validated" or "ready for manufacture".
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

SCHEMAS = {"ap214": "AP214IS", "ap242": "AP242DIS"}
DEFAULT_SCHEMA = "ap214"
STEP_TIMESTAMP = "2000-01-01T00:00:00"  # byte-identical re-exports of the same build
ZIP_DATE = (2020, 1, 1, 0, 0, 0)
VOLUME_REL_TOL = 1e-6
BBOX_TOL_MM = 1e-4
_STEP_LOCK = threading.Lock()  # OCCT's write.step.schema is process-global

DISCLOSURE = (
    "SOLIDWORKS imports this STEP file as a dumb solid (an 'Imported' feature): exact geometry, but no Formwright "
    "feature history, sketches or driving dimensions. The parameters in the CSV are a record of the design intent; "
    "they do not drive the imported body. To change the part, edit it in Formwright and export again.")
BRIDGE_NOTE = (
    "Native feature trees (sketches, features and global variables in the SOLIDWORKS FeatureManager) are planned "
    "in the Native CAD bridge (backlog); this export is the STEP pathway until then.")


class ExportRefused(ValueError):
    """The project cannot be exported (not built, not verified, or the written file failed its read-back)."""


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or ""))[:60].strip("_") or "part"


def body_colour(material: str | None) -> tuple[str, tuple[float, float, float]] | None:
    """(label, sRGB 0..1) for the body when the material text maps to a finish colour; None for unspecified."""
    from aicad.meshstudio import presets

    m = presets.map_material(material)
    if m["matched"] is None:
        return None
    f = presets.FINISHES[m["finish"]]
    table = f.get("colours")
    if table:
        label, hexc = table[m["colour"] if m["colour"] in table else f["default_colour"]]
        label = f"{f['label']}, {label}"
    else:
        label, hexc = f["label"], f["base"]
    h = hexc.lstrip("#")
    return label, (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def write_step(shape: Any, path: Path, name: str, schema: str = DEFAULT_SCHEMA,
               colour: tuple[float, float, float] | None = None) -> None:
    """Write ``shape`` as a SOLIDWORKS-friendly STEP: chosen schema, mm, named product/body, optional colour.

    An XCAF document with ONE named shape (``build123d.export_step`` wraps a solid in an assembly of one, which
    SOLIDWORKS opens as an assembly). The header is taken from the model after the transfer, so ``FILE_SCHEMA``
    matches the entities written (build123d's fallback header always says AP214)."""
    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.Message import Message, Message_Gravity
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Controller, STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_Controller, STEPControl_StepModelType
    from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool
    from OCP.XSControl import XSControl_WorkSession

    if schema not in SCHEMAS:
        raise ValueError(f"unknown STEP schema {schema!r}")
    with _STEP_LOCK:
        STEPCAFControl_Controller.Init_s()
        STEPControl_Controller.Init_s()
        saved = {k: Interface_Static.CVal_s(k) for k in ("write.step.schema", "write.surfacecurve.mode",
                                                            "write.precision.mode")}
        for printer in Message.DefaultMessenger_s().Printers():
            printer.SetTraceLevel(Message_Gravity.Message_Fail)
        try:
            Interface_Static.SetCVal_s("write.step.schema", SCHEMAS[schema])
            Interface_Static.SetIVal_s("write.surfacecurve.mode", 1)
            Interface_Static.SetIVal_s("write.precision.mode", 0)  # average
            # one free shape = one STEP product (SOLIDWORKS opens a part, not an assembly of one)
            doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
            app = XCAFApp_Application.GetApplication_s()
            app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
            app.InitDocument(doc)
            XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 0.001)  # millimetres
            occ = shape.wrapped
            loc = occ.Location()
            if not loc.IsIdentity():  # a located shape becomes an instance (assembly); bake the placement in
                occ = BRepBuilderAPI_Transform(occ.Located(TopLoc_Location()), loc.Transformation(), True).Shape()
            label = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()).AddShape(occ, False)
            TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
            if colour is not None:
                XCAFDoc_DocumentTool.ColorTool_s(doc.Main()).SetColor(
                    label, Quantity_Color(*colour, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorSurf)
            writer = STEPCAFControl_Writer(XSControl_WorkSession(), False)
            writer.SetColorMode(True)
            writer.SetLayerMode(True)
            writer.SetNameMode(True)
            if not writer.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs):
                raise ExportRefused("The model could not be converted to STEP.")
            header = APIHeaderSection_MakeHeader(writer.Writer().Model())
            if header.IsDone():
                header.SetName(TCollection_HAsciiString(name))
                header.SetTimeStamp(TCollection_HAsciiString(STEP_TIMESTAMP))
                header.SetOriginatingSystem(TCollection_HAsciiString("Formwright"))
            if writer.Write(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
                raise ExportRefused("The STEP file could not be written.")
        finally:
            for k, v in saved.items():
                Interface_Static.SetCVal_s(k, v)


def step_facts(path: Path) -> dict[str, Any]:
    """What the written file declares (read from the text, independent of the writer)."""
    import re

    txt = path.read_text(encoding="latin-1")
    schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", txt)
    names = re.findall(r"[=\s]PRODUCT\s*\(\s*'([^']*)'", txt)
    return {"schema": schema.group(1) if schema else None,
            "length_unit_mm": bool(re.search(r"SI_UNIT\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", txt)),
            "product_names": names,
            "has_colour": "STYLED_ITEM" in txt and "COLOUR" in txt,
            "assembly": "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in txt}


def _bbox(shape: Any) -> list[float]:
    bb = shape.bounding_box(optimal=True)
    return [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z]


def verify(original: Any, written: Path) -> dict[str, Any]:
    """Read the written STEP back and compare with the verified build's solid. Raises ExportRefused on mismatch."""
    from build123d import import_step

    back = import_step(str(written))
    v0, v1 = float(original.volume), float(back.volume)
    b0, b1 = _bbox(original), _bbox(back)
    n0, n1 = len(original.solids()), len(back.solids())
    ok = (abs(v1 - v0) <= VOLUME_REL_TOL * max(abs(v0), 1e-9) and n0 == n1
          and max(abs(a - b) for a, b in zip(b0, b1, strict=True)) <= BBOX_TOL_MM)
    res = {"volume_mm3": round(v1, 6), "bbox_minmax_mm": [round(x, 6) for x in b1], "solids": n1,
           "matches_build": ok}
    if not ok:
        raise ExportRefused("The exported file did not read back identical to the verified model, so it was not "
                            "offered. Please rebuild the part and try again.")
    return res


def parameter_rows(status: dict[str, Any]) -> list[dict[str, Any]]:
    params = status.get("params") or {}
    editable = status.get("editable_params") or {}
    meta = status.get("param_meta") or {}
    rows = []
    for k, v in params.items():
        if not isinstance(v, int | float) or isinstance(v, bool):
            continue
        m = meta.get(k) or {}
        rows.append({"parameter": k, "label": m.get("label", ""), "value": v, "unit": m.get("unit", ""),
                     "editable_in_formwright": "yes" if k in editable else "no",
                     "min": m.get("min", ""), "max": m.get("max", ""), "group": m.get("group", "")})
    return rows


def parameters_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    cols = ["parameter", "label", "value", "unit", "editable_in_formwright", "min", "max", "group"]
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def readme(name: str, status: dict[str, Any], schema: str, colour: str | None, check: dict[str, Any],
           rows: list[dict[str, Any]], step_name: str, csv_name: str, revision: Any = None) -> str:
    checks = [c for c in status.get("checks") or [] if isinstance(c, dict)]
    gating = [c for c in checks if c.get("gating", True)]
    passed = sum(1 for c in gating if c.get("passed"))
    bb = check["bbox_minmax_mm"]
    lines = [
        f"{name}: export for SOLIDWORKS (STEP pathway)",
        "",
        "WHAT YOU GET",
        f"  {step_name}  STEP {SCHEMAS[schema][:5]}, millimetres, one solid body named '{name}'"
        + (f", colour from the material ({colour})" if colour else "") + ".",
        f"  {csv_name}  the model's parameters (design intent, for reference).",
        "",
        "IMPORTANT",
        "  " + DISCLOSURE,
        "  " + BRIDGE_NOTE,
        "",
        "OPENING IT IN SOLIDWORKS",
        "  File > Open, choose 'STEP AP203/214/242 (*.step;*.stp)', select the file. If SOLIDWORKS asks to run",
        "  Import Diagnostics you can accept it; the solid is already closed and valid in Formwright's checks.",
        "  Units: the file declares millimetres; use an MMGS part template so dimensions read in mm.",
        "",
        "CHECKED BEFORE THIS FILE WAS OFFERED",
        (f"  Read back with the same kernel that wrote it: volume {check['volume_mm3']:.3f} mm3, "
        f"{check['solids']} solid(s), bounding box min ({bb[0]:.3f}, {bb[1]:.3f}, {bb[2]:.3f}) "
        f"max ({bb[3]:.3f}, {bb[4]:.3f}, {bb[5]:.3f}) mm - identical to the verified model."),
        f"  Formwright gating checks on this build: {passed} of {len(gating)} passed"
        + (f" (revision {revision})" if revision is not None else "") + ".",
        "  This export has not been opened in SOLIDWORKS by Formwright; a different STEP reader can still differ.",
        "  The geometry is a design model. Engineer review is required before manufacture.",
        "",
        "PARAMETERS",
    ]
    if rows:
        for r in rows:
            unit = f" {r['unit']}" if r["unit"] else ""
            label = f" ({r['label']})" if r["label"] else ""
            lines.append(f"  {r['parameter']}{label} = {r['value']}{unit}")
    else:
        lines.append("  This model declares no parameters.")
    lines += ["", f"Material: {status.get('material') or 'not specified'}", ""]
    return "\n".join(lines)


def build_package(out_dir: Path, name: str, schema: str = DEFAULT_SCHEMA, revision: Any = None) -> tuple[bytes, dict[str, Any]]:
    """The zip for a project's verified build (``out_dir`` = ``<workspace>/out``). Returns (zip bytes, facts)."""
    from build123d import import_step

    schema = (schema or DEFAULT_SCHEMA).lower()
    if schema not in SCHEMAS:
        raise ExportRefused("Choose AP214 or AP242.")
    try:
        status = json.loads((out_dir / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ExportRefused("This project has no verified model yet. Build it in the Design Studio first.") from e
    src = out_dir / "part.step"
    if not status.get("ok") or not src.is_file():
        raise ExportRefused("Only a model that passed its checks can be exported. Fix the failing checks first.")
    shape = import_step(str(src))
    solids = shape.solids()
    if len(solids) == 1:  # one product, one body: SOLIDWORKS opens it as a part, not an assembly of one
        shape = solids[0]
    col = body_colour(status.get("material"))
    stem = safe_name(name)
    step_name, csv_name = f"{stem}.step", f"{stem}_parameters.csv"
    with tempfile.TemporaryDirectory(prefix="fw-sw-") as tmp:
        p = Path(tmp) / step_name
        write_step(shape, p, name or "Part", schema, col[1] if col else None)
        check = verify(import_step(str(src)), p)
        facts = step_facts(p)
        step_bytes = p.read_bytes()
    rows = parameter_rows(status)
    files = {step_name: step_bytes, csv_name: parameters_csv(rows).encode("utf-8"),
             "README_SOLIDWORKS.txt": readme(name or "Part", status, schema, col[0] if col else None, check, rows,
                                             step_name, csv_name, revision).replace("\n", "\r\n").encode("utf-8")}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, data in files.items():
            zi = zipfile.ZipInfo(fname, date_time=ZIP_DATE)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, data)
    return buf.getvalue(), {"schema": schema, "step": facts, "check": check, "colour": col[0] if col else None,
                            "parameters": len(rows), "files": list(files)}
