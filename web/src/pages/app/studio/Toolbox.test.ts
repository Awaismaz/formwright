import { describe, expect, it } from "vitest";
import { templateValues, type TplParam } from "./Toolbox";

const P = (name: string, value: number): TplParam => ({ name, value, label: name, unit: "mm", group: "", min: null, max: null });

describe("starting a Studio part from a workspace template", () => {
  it("sends only the sizes the engineer changed, as numbers", () => {
    const params = [P("OD", 50), P("LENGTH", 200), P("BORE", 20)];
    expect(templateValues(params, { OD: "60", LENGTH: "200", BORE: "" })).toEqual({ OD: 60 });
    expect(templateValues(params, { OD: "abc", LENGTH: " 120 " })).toEqual({ LENGTH: 120 });
    expect(templateValues(params, {})).toEqual({});
  });
});
