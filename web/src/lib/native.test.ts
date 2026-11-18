import { describe, expect, it } from "vitest";
import { describe as summarize, dispositionName, fileSize, formatOf, isNativeFile, KIND_EXT, moduleExportUrl, NATIVE_ACCEPT, NATIVE_EXTS, overallState, resultLink, type ImportResult, type Verification } from "./native";

const v = (state: Verification["state"]): { verification: Verification } => ({ verification: { state, label: state, diffs: [] } });

describe("native file helpers", () => {
  it("recognises Formwright files and archives", () => {
    expect(isNativeFile("Bracket.fwpart")).toBe(true);
    expect(isNativeFile("ASM.FWASM")).toBe(true);
    expect(isNativeFile("projects.zip")).toBe(true);
    expect(isNativeFile("part.step")).toBe(false);
    expect(formatOf("a.b.fwdrw")).toBe("fwdrw");
    expect(formatOf("notes.txt")).toBeNull();
  });

  it("opens each import where it belongs", () => {
    const base = { trust: "workspace", format: "fwpart" as const, warnings: [] as string[] };
    expect(resultLink({ ...base, kind: "part", project: { id: "p1", name: "x" } } as ImportResult)).toBe("/app/projects/p1");
    expect(resultLink({ ...base, kind: "assembly", assembly: { id: "a1", name: "x" } } as ImportResult)).toBe("/app/modules/assembly?assembly=a1");
    expect(resultLink({ ...base, kind: "drawing", project: { id: "p2", name: "x" } } as ImportResult)).toBe("/app/modules/drawings?project=p2");
    expect(resultLink({ ...base, kind: "program", program: { id: "g1", name: "x" } } as ImportResult)).toBe("/app/office/programs/g1");
    expect(resultLink({ ...base, kind: "projects", parts: [] } as ImportResult)).toBe("/app/projects");
  });

  it("an assembly is identical only when every part is", () => {
    expect(overallState([v("identical"), v("identical")])).toBe("identical");
    expect(overallState([v("identical"), v("mismatch")])).toBe("mismatch");
    expect(overallState([v("mismatch"), v("fallback")])).toBe("fallback");
    expect(overallState([])).toBe("identical");
  });

  it("describes a file in one plain line", () => {
    expect(summarize({ kind: "part", title: "B", material: "6061", parameters: 1, features: 3, revisions: 2 }))
      .toBe("6061 · 1 parameter · 3 features · 2 revisions");
    expect(summarize({ kind: "assembly", title: "A", instances: 4, mates: 1, parts: [{ ref: "a", kind: "project", name: "x" }] }))
      .toBe("4 instances · 1 mate · 1 distinct part");
    expect(summarize({ kind: "drawing", title: "D", model: true, part: "Plate", sheet: "A3", scale: "1:2" })).toBe("drawing of Plate · A3, 1:2");
  });

  it("reads the download name and sizes", () => {
    expect(dispositionName('attachment; filename="Plate.fwpart"', "x")).toBe("Plate.fwpart");
    expect(dispositionName(null, "fallback.fwpart")).toBe("fallback.fwpart");
    expect(fileSize(512)).toBe("512 B");
    expect(fileSize(2048)).toBe("2 KB");
    expect(fileSize(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("covers every module's file", () => {
    expect(NATIVE_EXTS.length).toBe(9);
    for (const e of NATIVE_EXTS) { expect(isNativeFile(`x.${e}`)).toBe(true); expect(NATIVE_ACCEPT).toContain(`.${e}`); }
    expect(Object.values(KIND_EXT).every(e => e && (NATIVE_EXTS as readonly string[]).includes(e))).toBe(true);
    const base = { trust: "foreign", format: "fwmfg" as const, warnings: [] as string[] };
    expect(resultLink({ ...base, kind: "mfg", project: { id: "p", name: "x" } } as ImportResult)).toBe("/app/modules/manufacturing?project=p");
    expect(resultLink({ ...base, kind: "ai", project: { id: "p", name: "x" } } as ImportResult)).toBe("/app/modules/airender?project=p");
    expect(resultLink({ ...base, kind: "draft", draft: { id: "d", name: "x" } } as ImportResult)).toBe("/app/modules/drawings?draft=d");
    expect(resultLink({ ...base, kind: "read", upload: { id: "u", name: "x" } } as ImportResult)).toBe("/app/modules/image2cad?upload=u");
    expect(resultLink({ ...base, kind: "upload", upload: { id: "u", name: "x" } } as ImportResult)).toBe("/app/modules/print?upload=u");
    expect(moduleExportUrl("calc", "p1")).toBe("/api/native/modules/calc/p1/export");
  });
});
