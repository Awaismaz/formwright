import { describe, expect, it } from "vitest";
import { errorFrom } from "./api";

describe("errorFrom", () => {
  it("explains a route the server doesn't have yet (page newer than server) instead of 'Method Not Allowed'", () => {
    expect(errorFrom(405, { detail: "Method Not Allowed" }).message).toMatch(/being updated/);
    expect(errorFrom(404, { detail: "Not Found" }).message).toMatch(/being updated/);
  });
  it("keeps the server's own messages", () => {
    expect(errorFrom(404, { detail: "Program not found" }).message).toBe("Program not found");
    expect(errorFrom(409, { detail: { message: "Busy", cta: "/x" } }).cta).toBe("/x");
  });
});
