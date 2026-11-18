"""Regenerate the landing page's 3D parts (web/public/landing/*.glb) from the real Formwright Toolbox.

Run from the repo root:  unset VIRTUAL_ENV && uv run python scripts/landing_assets.py
GLB is in metres, Y up (build123d export); the landing viewer scales back to millimetres.
"""

from __future__ import annotations

from pathlib import Path

from build123d import export_gltf

from aicad import toolbox
from aicad.toolbox import _cyl

OUT = Path(__file__).resolve().parents[1] / "web" / "public" / "landing"
FLANGE = {"OD": 150, "T": 16, "BORE": 60, "N": 6, "HOLE": 14, "PCD": 120}


def save(name: str, shape: object, lin: float = 0.05, ang: float = 0.25) -> None:
    path = OUT / f"{name}.glb"
    export_gltf(shape, str(path), binary=True, linear_deflection=lin, angular_deflection=ang)
    print(f"{path.name:20s} {path.stat().st_size / 1024:7.1f} KB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # hero build stages: blank disc -> bored disc -> finished flange (the Toolbox part)
    save("flange-blank", _cyl(FLANGE["OD"] / 2, FLANGE["T"]))
    save("flange-bore", _cyl(FLANGE["OD"] / 2, FLANGE["T"]) - _cyl(FLANGE["BORE"] / 2, FLANGE["T"] + 0.02, -0.01))
    save("flange", toolbox.build("flange", **FLANGE)[0])
    # Toolbox carousel, recognition and the bolted-joint assembly
    save("gear", toolbox.build("spur_gear", M=2, Z=24, B=12, BORE=10)[0], 0.2, 0.6)
    save("bearing", toolbox.build("bearing", SERIES=6204)[0], 0.1, 0.6)
    save("hex_bolt", toolbox.build("hex_bolt", D=12, L=55)[0])
    save("hex_nut", toolbox.build("hex_nut", D=12)[0])
    save("washer", toolbox.build("washer", D=12)[0])
    save("shcs", toolbox.build("shcs", D=8, L=30)[0])


if __name__ == "__main__":
    main()
