import { describe, expect, it } from "vitest";
import { TOASTER_PROPS } from "./toaster";

describe("toasts never cover the primary content", () => {
  it("sit bottom right, narrow, few at a time, and can be closed", () => {
    expect(TOASTER_PROPS.position).toBe("bottom-right");
    expect(TOASTER_PROPS.closeButton).toBe(true);
    expect(TOASTER_PROPS.visibleToasts).toBeLessThanOrEqual(3);
    expect(TOASTER_PROPS.toastOptions.style.maxWidth).toContain("360px");
  });
});
