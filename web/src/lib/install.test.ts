import { describe, expect, it } from "vitest";
import { DISMISS_DAYS, DISMISS_KEY, detectPlatform, dismiss, installMode, isDismissed, isStandalone, showBanner } from "./install";

const UA = {
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  ipadOS: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
  android: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
  windows: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
};

function mem(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

describe("detectPlatform", () => {
  it("recognises iPhone, Android and desktop", () => {
    expect(detectPlatform(UA.iphone, 5)).toBe("ios");
    expect(detectPlatform(UA.android, 5)).toBe("android");
    expect(detectPlatform(UA.windows, 0)).toBe("desktop");
  });
  it("treats a touch 'Macintosh' as an iPad (iPadOS desktop UA) but a real Mac as desktop", () => {
    expect(detectPlatform(UA.ipadOS, 5)).toBe("ios");
    expect(detectPlatform(UA.ipadOS, 0)).toBe("desktop");
  });
});

describe("standalone and mode", () => {
  it("detects the installed app by display-mode or navigator.standalone", () => {
    expect(isStandalone(true)).toBe(true);
    expect(isStandalone(false, true)).toBe(true);
    expect(isStandalone(false, undefined)).toBe(false);
    expect(isStandalone(false, false)).toBe(false);
  });
  it("offers nothing once installed, the prompt when the browser gives one, steps on iOS", () => {
    expect(installMode({ platform: "android", standalone: true, hasPrompt: true })).toBe("installed");
    expect(installMode({ platform: "android", standalone: false, hasPrompt: true })).toBe("prompt");
    expect(installMode({ platform: "desktop", standalone: false, hasPrompt: true })).toBe("prompt");
    expect(installMode({ platform: "ios", standalone: false, hasPrompt: false })).toBe("ios");
    expect(installMode({ platform: "ios", standalone: true, hasPrompt: false })).toBe("installed");
    expect(installMode({ platform: "desktop", standalone: false, hasPrompt: false })).toBe("unavailable");
  });
});

describe("dismissal", () => {
  it("remembers a dismissal, and offers again after the quiet period", () => {
    const s = mem();
    const t0 = 1_700_000_000_000;
    expect(isDismissed(s, t0)).toBe(false);
    dismiss(s, t0);
    expect(s.m.get(DISMISS_KEY)).toBe(String(t0));
    expect(isDismissed(s, t0 + 86_400_000)).toBe(true);
    expect(isDismissed(s, t0 + (DISMISS_DAYS + 1) * 86_400_000)).toBe(false);
  });
  it("survives storage that throws or holds junk", () => {
    const bad = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    expect(isDismissed(bad)).toBe(false);
    expect(() => dismiss(bad)).not.toThrow();
    expect(isDismissed(mem({ [DISMISS_KEY]: "yes" }))).toBe(true);
    expect(isDismissed(null)).toBe(false);
  });
  it("shows the mobile banner only on phones/tablets that can install and haven't dismissed it", () => {
    expect(showBanner("ios", "ios", false)).toBe(true);
    expect(showBanner("prompt", "android", false)).toBe(true);
    expect(showBanner("prompt", "android", true)).toBe(false);
    expect(showBanner("prompt", "desktop", false)).toBe(false);
    expect(showBanner("installed", "ios", false)).toBe(false);
    expect(showBanner("unavailable", "android", false)).toBe(false);
  });
});
