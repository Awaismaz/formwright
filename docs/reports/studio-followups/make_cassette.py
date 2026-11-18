"""Builds cassette.json for the studio-followups walkthrough (replayed agent, zero model calls)."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests"))
from test_studio_intel import BOX, HOLES2, LPAT, PIN, PLATE, POCKET  # noqa: E402

from aicad.platform.routers.studio import write_manual  # noqa: E402

here = Path(__file__).parent
base = json.loads((here.parents[0] / "studio-intel" / "cassette.json").read_text(encoding="utf-8"))["turns"]
build = base[0]


def build_turn(match: str, src: str, say: str) -> dict:
    t = copy.deepcopy(build)
    t["match"] = match
    t["files"] = {"model.py": src}
    for m in t["messages"]:
        for c in m.get("content", []) if isinstance(m.get("content"), list) else []:
            if c.get("type") == "text":
                c["text"] = say
    return t


boss = {"id": "b1", "op": "extrude", "name": "Boss", "suppressed": False,
        "plane": {"origin": [50.0, 30.0, 10.0], "normal": [0.0, 0.0, 1.0]},
        "sketch": {"kind": "rect", "w": 10.0, "h": 10.0, "cx": 0.0, "cy": 0.0}, "distance": 3.0, "mode": "add",
        "end": "blind", "reverse": False}
hole = {"id": "h1", "op": "hole", "name": "Pin hole", "suppressed": False, "point": [50.0, 30.0, 13.0],
        "normal": [0.0, 0.0, 1.0], "d": 6.6, "depth": None}
multi = ("Two changes, one panel each: the pocket depth, then the pattern.\n```fw-edit\n"
         + json.dumps({"summary": "Deeper pockets, four of them", "edits": [
             {"op": "extrude", "feature": "Pocket", "distance": 5},
             {"op": "pattern", "feature": "LPattern1", "count": 4, "spacing": 12}]}) + "\n```")
turns = [
    build_turn("^Build the pocket box", write_manual(BOX, [POCKET, LPAT, HOLES2]), "Built the pocket box."),
    build_turn("^Build the base plate", write_manual(PLATE.replace("HOLES = 4", "HOLES = 0"), [boss, hole]),
               "Built the base plate with a boss and a pin hole."),
    build_turn("^Build the pin", PIN, "Built the pin."),
    {**copy.deepcopy(base[3]), "match": "pockets"},
]
turns[3]["messages"][1]["content"][0]["text"] = multi
(here / "cassette.json").write_text(json.dumps({"version": 1, "turns": turns}, indent=1), encoding="utf-8")
print("ok", len(turns))
