import { describe, expect, it } from "vitest";
import { atLeast, blockingLock, can, featureText, mentionSegments, paramRows, presenceRows, readyToMerge, whyNot, type Access } from "./collab";

const acc = (o: Partial<Access>): Access => ({
  level: "edit", source: "workspace", guest: false, team: null, general: "edit", can_read: true, can_comment: true, can_edit: true,
  can_admin: false, can_agent: true, protected_main: false, required_approvals: 1, ...o,
});

describe("permissions", () => {
  it("orders levels", () => {
    expect(atLeast("admin", "edit")).toBe(true);
    expect(atLeast("comment", "edit")).toBe(false);
    expect(atLeast(undefined, "read")).toBe(false);
  });
  it("maps actions to levels", () => {
    const read = acc({ level: "read", can_edit: false, can_comment: false, can_agent: false });
    expect(can(read, "view")).toBe(true);
    expect(can(read, "comment")).toBe(false);
    expect(can(read, "edit")).toBe(false);
    expect(can(acc({ level: "comment" }), "comment")).toBe(true);
    expect(can(acc({}), "share")).toBe(false);
    expect(can(acc({ level: "admin" }), "delete")).toBe(true);
  });
  it("guests never run the agent, even with edit", () => {
    const g = acc({ guest: true, can_agent: false });
    expect(can(g, "edit")).toBe(true);
    expect(can(g, "agent")).toBe(false);
    expect(whyNot(g, "agent")).toMatch(/Guests/);
  });
  it("protected main sends editors to a branch, not admins", () => {
    const p = acc({ protected_main: true });
    expect(can(p, "edit", "main")).toBe(false);
    expect(can(p, "edit", "b1")).toBe(true);
    expect(whyNot(p, "edit", "main")).toMatch(/protected/);
    expect(can(acc({ protected_main: true, level: "admin" }), "edit", "main")).toBe(true);
  });
  it("explains a missing level", () => {
    expect(whyNot(acc({ level: "read" }), "edit")).toMatch(/view access/);
    expect(whyNot(acc({}), "share")).toMatch(/admins/);
    expect(whyNot(acc({}), "edit")).toBeNull();
  });
  it("keeps old behaviour without access info", () => {
    expect(can(undefined, "edit")).toBe(true);
    expect(can(undefined, "share")).toBe(false);
  });
});

describe("presence and locks", () => {
  const users = [{ user_id: "me", name: "Me", branches: ["main"], since: "" }, ...["a", "b", "c", "d", "e"].map(u => ({ user_id: u, name: u, branches: ["main"], since: "" }))];
  it("hides me and overflows", () => {
    const r = presenceRows(users, "me", 3);
    expect(r.shown.map(u => u.user_id)).toEqual(["a", "b", "c"]);
    expect(r.more).toBe(2);
  });
  it("finds the lock that blocks me on my branch only", () => {
    const locks = [{ user_id: "a", name: "Ada", what: "design agent running", branch: "main" }];
    expect(blockingLock(locks, "main", "me")?.name).toBe("Ada");
    expect(blockingLock(locks, "b1", "me")).toBeNull();
    expect(blockingLock(locks, "main", "a")).toBeNull();
  });
});

describe("merge request diffs", () => {
  it("builds parameter rows and flags conflicts", () => {
    const rows = paramRows({ T: { from: 10, to: 12 }, W: { from: 80, to: 90 } }, { T: { from: 10, to: 11 }, L: { from: 120, to: 140 } },
      { T: { label: "Thickness", unit: "mm" } });
    const t = rows.find(r => r.key === "T")!;
    expect(t).toMatchObject({ label: "Thickness", base: 10, main: 11, branch: 12, conflict: true });
    expect(rows.find(r => r.key === "L")).toMatchObject({ main: 140, branch: 120, changedOnBranch: false, conflict: false });
    expect(rows.find(r => r.key === "W")).toMatchObject({ main: 80, branch: 90, conflict: false });
  });
  it("describes feature changes in plain words", () => {
    expect(featureText({ id: "1", name: "Fillet1", op: "fillet", change: "added", fields: [] })).toBe("Added Fillet1");
    expect(featureText({ id: "1", name: "Hole1", op: "hole", change: "edited", fields: ["diameter", "suppressed"] })).toBe("Edited Hole1 (diameter, suppression)");
  });
  it("needs a usable choice for every conflict", () => {
    const cs = [{ id: "param:T" }, { id: "source:1" }];
    expect(readyToMerge(cs, { "param:T": "theirs" }, [])).toBe(false);
    expect(readyToMerge(cs, { "param:T": "theirs", "source:1": "agent" }, [])).toBe(false);
    expect(readyToMerge(cs, { "param:T": "theirs", "source:1": "agent" }, ["source:1"])).toBe(true);
  });
});

describe("mentions", () => {
  it("splits @mentions of known people", () => {
    const segs = mentionSegments("@Ada can you and @bob check? mail me@x.com", [{ id: "1", name: "Ada Lovelace" }, { id: "2", name: "Bob Builder" }]);
    expect(segs.filter(s => s.mention).map(s => s.text)).toEqual(["@Ada", "@bob"]);
    expect(segs.map(s => s.text).join("")).toBe("@Ada can you and @bob check? mail me@x.com");
  });
});
