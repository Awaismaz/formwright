import { describe, expect, it } from "vitest";
import { icdRows, reviewMarks, rowDiameters, rowKind, sentBackReason, stageView, workStage } from "./model";
import { parseThumb } from "./thumbs";
import type { Ticket } from "./types";

const T = (o: Partial<Ticket>) => ({ column: "in_design", run_status: "designing", line: null, title: "Output shaft", ...o }) as Ticket;

describe("stage reveal from the status line", () => {
  it("follows the agent's own words", () => {
    expect(workStage(T({ column: "ready", run_status: null }))).toBe("waiting");
    expect(workStage(T({ line: "Chuck is reading the brief for Output shaft" }))).toBe("reading");
    expect(workStage(T({ run_status: "searching", line: "Hex is looking in the Toolbox" }))).toBe("reading");
    expect(workStage(T({ line: "Chuck is turning Output shaft" }))).toBe("rough");
    expect(workStage(T({ line: "Axel is hobbing Gear" , title: "Gear"}))).toBe("rough");
    expect(workStage(T({ line: "Chuck is facing and grooving Output shaft" }))).toBe("features");
    expect(workStage(T({ line: "Chuck is re-turning Output shaft: a check failed" }))).toBe("features");
    expect(workStage(T({ line: "Output shaft passes the gating checks: Chuck is chamfering" }))).toBe("finish");
    expect(workStage(T({ line: "Chuck is miking Output shaft against the brief" }))).toBe("measure");
    expect(workStage(T({ line: "Mill is building Output shaft from the interface spec (no AI)" }))).toBe("direct");
    expect(workStage(T({ column: "in_review", run_status: "reviewing", line: "Gage is inspecting Output shaft against the brief" }))).toBe("inspect");
    expect(workStage(T({ column: "approved", run_status: "fitting", line: "Fitz is swapping Output shaft in for its placeholder" }))).toBe("fit");
    expect(workStage(T({ column: "integrated", run_status: "done" }))).toBe("done");
    expect(workStage(T({ column: "changes_requested", run_status: "designing" }))).toBe("sent_back");
    expect(workStage(T({ run_status: "blocked" }))).toBe("sent_back");
    expect(workStage(T({ column: "in_review", run_status: "awaiting_review" }))).toBe("review");
  });
  it("never reads the part's own title as a stage", () => {
    expect(workStage(T({ title: "Turning bracket", line: "Mill is reading the brief for Turning bracket" }))).toBe("reading");
    expect(workStage(T({ title: "Bending jig", line: "Mill is roughing out Bending jig" }))).toBe("rough");
  });
  it("lights the envelope first, then the profile, then holes, then chamfers", () => {
    expect(stageView("waiting")).toMatchObject({ show: "ghost", lit: [], faint: true, scan: false });
    expect(stageView("reading").lit).toEqual(["envelope"]);
    expect(stageView("rough").lit).toEqual(["envelope", "profile", "teeth"]);
    expect(stageView("features").lit).toEqual(expect.arrayContaining(["bore", "keyway", "groove"]));
    expect(stageView("features").lit).not.toContain("chamfer");
    expect(stageView("finish").lit).toContain("chamfer");
    expect(stageView("inspect").scan).toBe(true);
    expect(stageView("measure").scan).toBe(true);
    expect(stageView("done").show).toBe("real");
    expect(stageView("fit").show).toBe("real");
  });
});

describe("Gage's rows ticked onto the thumbnail", () => {
  it("knows the feature kind of every ICD label", () => {
    expect(rowKind("hole 1")).toBe("bore");
    expect(rowKind("tapped hole 2 M6 × 12 deep")).toBe("bore");
    expect(rowKind("bearing seat Ø47 H7 (top)")).toBe("bore");
    expect(rowKind("shaft clearance Ø24")).toBe("bore");
    expect(rowKind("bearing journal Ø20 k6")).toBe("profile");
    expect(rowKind("shaft Ø20 k6")).toBe("profile");
    expect(rowKind("seat Ø25 k6 (stepped shaft)")).toBe("profile");
    expect(rowKind("keyway 6 × 3.5 (shaft, DIN 6885)")).toBe("keyway");
    expect(rowKind("retaining ring groove Ø18.6 × 1.3 H13 (DIN 471 20)")).toBe("groove");
    expect(rowKind("m2 × 40 teeth")).toBe("teeth");
    expect(rowKind("mounting face")).toBe("envelope");
    expect(rowKind("envelope")).toBe("envelope");
  });
  it("reads the diameters a row can match", () => {
    expect(rowDiameters({ feature: "bore Ø20 H7", spec: "Ø20 H7 on the axis at (0, 0)", d_mm: 20.4 })).toEqual([20, 20.4]);
    expect(rowDiameters({ feature: "hole 1", spec: "Ø6.6 at (-16.8, -6.8)" })).toEqual([6.6]);
    expect(rowDiameters({ feature: "mounting face", spec: "plane Z 4" })).toEqual([]);
  });
  it("marks groups by kind and diameter; a fail wins; unmatched rows mark nothing", () => {
    const groups = [{ g: 0, feature: "envelope" }, { g: 1, feature: "bore", d: 6.6 }, { g: 2, feature: "bore", d: 6.6 },
      { g: 3, feature: "bore", d: 20 }, { g: 4, feature: "keyway" }, { g: 5, feature: "profile", d: 25 }];
    const m = reviewMarks([
      { feature: "hole 1", spec: "Ø6.6 at (1, 1)", ok: true }, { feature: "hole 2", spec: "Ø6.6 at (2, 2)", ok: false, d_mm: 6.6 },
      { feature: "bore Ø20 H7", spec: "Ø20 H7 on the axis", ok: true }, { feature: "keyway 6 × 3.5 (hub, DIN 6885)", spec: "6 wide", ok: true },
      { feature: "envelope", spec: "inside 60 × 40 × 8 mm", ok: true }, { feature: "bearing journal Ø17 k6", spec: "Ø17 k6", ok: false },
    ], groups);
    expect(m.get(1)).toBe("fail");
    expect(m.get(2)).toBe("fail");
    expect(m.get(3)).toBe("ok");
    expect(m.get(4)).toBe("ok");
    expect(m.get(0)).toBe("ok");
    expect(m.has(5)).toBe(false); // the Ø17 journal is not the Ø25 profile drawn
  });
  it("puts a turned part's envelope on its largest diameter", () => {
    const shaft = [{ g: 1, feature: "profile", d: 26 }, { g: 2, feature: "profile", d: 20 }, { g: 3, feature: "keyway" }];
    const m = reviewMarks([{ feature: "envelope", spec: "inside 26 × 26 × 80 mm", ok: false }], shaft);
    expect([...m.entries()]).toEqual([[1, "fail"]]);
  });
  it("names the failing feature on a sent-back card", () => {
    const icd_check = { version: 1, ok: false, envelope: { feature: "envelope", spec: "", measured: "", ok: true },
      interfaces: [{ interface: "IF-01", name: "x", ok: false, rows: [{ feature: "bore Ø20 H7", spec: "Ø20 H7", measured: "Ø20.4", ok: false }] }] };
    expect(icdRows({ icd_check }).length).toBe(2);
    expect(sentBackReason({ icd_check, column: "changes_requested", run: null, run_status: "designing" })).toBe("Off: bore Ø20 H7");
    // sent back and being reworked: the chip stays until Gage measures it again
    expect(sentBackReason({ icd_check, column: "in_design", run: null, run_status: "designing" })).toBe("Off: bore Ø20 H7");
    expect(sentBackReason({ icd_check: { ...icd_check, ok: true }, column: "in_design", run: null, run_status: "designing" })).toBeNull();
    expect(sentBackReason({ icd_check, column: "integrated", run: null, run_status: "done" })).toBeNull();
    expect(sentBackReason({ icd_check: null, column: "in_design", run: { blocked: "Out of tokens" }, run_status: "blocked" })).toBe("Out of tokens");
  });
});

describe("thumbnail SVG parsing", () => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" data-fw-thumb="1" data-view="iso" fill="none">'
    + '<g data-feature="envelope" data-g="0"><path vector-effect="non-scaling-stroke" d="M1 2 L3 4"/></g>'
    + '<g data-feature="bore" data-g="3" data-d="6.6"><path data-hidden="1" stroke-width=".7" d="M5 5 L6 6"/><path vector-effect="non-scaling-stroke" d="M7 7 L8 8"/></g>'
    + '<g data-feature="bogus" data-g="4"><path d="M0 0 L1 1"/></g>'
    + '<g data-feature="keyway" data-g="5"><path d="M0 0 L1 1 onload=x"/></g></svg>';
  it("keeps our groups and path data only", () => {
    const t = parseThumb(svg)!;
    expect(t.viewBox).toBe("0 0 100 100");
    expect(t.groups.map(g => [g.feature, g.g, g.d])).toEqual([["envelope", 0, null], ["bore", 3, 6.6], ["keyway", 5, null]]);
    expect(t.groups[1]).toMatchObject({ vis: "M7 7 L8 8", hid: "M5 5 L6 6" });
    expect(t.groups[2]!.vis).toBe(""); // anything that isn't plain path data is dropped
    expect(parseThumb("<svg viewBox='0 0 1 1'></svg>")).toBeNull();
  });
});
