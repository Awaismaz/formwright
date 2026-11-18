/** Collaboration types and pure helpers (permissions, diffs, presence). Kept free of React for unit tests. */

export type Level = "none" | "read" | "comment" | "edit" | "admin";
export const LEVELS: Level[] = ["none", "read", "comment", "edit", "admin"];
export const GRANT_LEVELS: Exclude<Level, "none" | "admin">[] = ["read", "comment", "edit"];

export interface Access {
  level: Level; source: string; guest: boolean; team: { id: string; name: string; color: string } | null; general: Level;
  can_read: boolean; can_comment: boolean; can_edit: boolean; can_admin: boolean; can_agent: boolean;
  protected_main: boolean; required_approvals: number;
}

export interface Lock { user_id: string | null; name: string; what: string; branch: string; branch_name?: string }
export interface PresenceUser { user_id: string; name: string; branches: string[]; branch_names?: string[]; since: string; editing?: Lock | null }
export interface CollabState {
  access: Access; branch: { id: string; name: string }; users: PresenceUser[]; locks: Lock[];
  open_merge_requests: { id: string; number: number; title: string; branch_id: string }[]; comments: number;
}
export interface BranchInfo {
  id: string; name: string; status: "open" | "merged" | "closed"; source: string | null; base_rev: number | null;
  created_by: string | null; created_at: string; head: { revision: number | null; latest: number | null; ok: boolean | null } | null;
  lock: Lock | null; merge_request: { id: string; number: number; status: string } | null;
}

export type Action = "view" | "comment" | "edit" | "agent" | "share" | "delete" | "merge" | "approve";

const NEED: Record<Action, Level> = { view: "read", comment: "comment", edit: "edit", agent: "edit", share: "admin", delete: "admin", merge: "edit", approve: "edit" };

export const rank = (l: Level) => LEVELS.indexOf(l);
export const atLeast = (have: Level | undefined, need: Level) => rank(have ?? "none") >= rank(need);

/** Can this person do `action`? Projects made before permissions existed (no access info) keep the old behaviour. */
export function can(access: Access | undefined | null, action: Action, branch = "main"): boolean {
  if (!access) return action !== "share" && action !== "delete";
  if (action === "agent" && (access.guest || !access.can_agent)) return false;
  if ((action === "edit" || action === "agent") && branch === "main" && access.protected_main && access.level !== "admin") return false;
  return atLeast(access.level, NEED[action]);
}

/** The tooltip shown on a locked control: why it's off and what to do. */
export function whyNot(access: Access | undefined | null, action: Action, branch = "main"): string | null {
  if (can(access, action, branch) || !access) return null;
  if (action === "agent" && access.guest) return "Guests can't run the design agent on a shared project.";
  if ((action === "edit" || action === "agent") && branch === "main" && access.protected_main && atLeast(access.level, "edit"))
    return "Main is protected: work on a branch and open a merge request.";
  const need = NEED[action];
  return `You have ${LEVEL_TEXT[access.level].toLowerCase()} access. ${need === "admin" ? "Only the project's admins" : `People with ${need} access`} can do this.`;
}

export const LEVEL_TEXT: Record<Level, string> = { none: "No", read: "View", comment: "Comment", edit: "Edit", admin: "Admin" };
export const LEVEL_HELP: Record<Level, string> = {
  none: "No access", read: "Can view the part, its checks, revisions and drawings", comment: "Can view and comment",
  edit: "Can change the part (parameters, features, design agent)", admin: "Can edit, share and delete",
};
export const TEAM_ROLE_HELP: Record<string, string> = {
  admin: "Manages the team and gets admin on its projects", editor: "Edits the team's projects", viewer: "Views the team's projects",
};

export function lockText(l: Lock, me?: string | null): string {
  if (me && l.user_id === me) return `You are editing ${l.branch_name ?? l.branch} (${l.what})`;
  return `${l.name} is editing ${l.branch === "main" ? "main" : (l.branch_name ?? "a branch")} (${l.what})`;
}

/** The lock that stops *me* editing the branch I'm on, if any. */
export function blockingLock(locks: Lock[], branch: string, me?: string | null): Lock | null {
  return locks.find(l => l.branch === branch && l.user_id !== me) ?? null;
}

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]!.toUpperCase()).join("") || "?";
}

/** Presence avatars: me last-free, most recent first, with an overflow count. */
export function presenceRows(users: PresenceUser[], me: string | null | undefined, max = 4): { shown: PresenceUser[]; more: number } {
  const others = users.filter(u => u.user_id !== me);
  return { shown: others.slice(0, max), more: Math.max(0, others.length - max) };
}

// ------------------------------------------------------------------ merge request diffs
export interface ParamDiff { [k: string]: { from: number | null; to: number | null } }
export interface FeatureChange { id: string; name: string; op: string | null; change: "added" | "removed" | "edited"; fields: string[] }

export function fmtNum(v: number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined) return "—";
  const s = Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  return unit ? `${s} ${unit}` : s;
}

/** Rows for the parameter table: what main and the branch each changed since the branch started. */
export function paramRows(branch: ParamDiff, main: ParamDiff, meta: Record<string, { label?: string | null; unit?: string | null }>) {
  const keys = [...new Set([...Object.keys(branch), ...Object.keys(main)])].sort();
  return keys.map(k => {
    const b = branch[k], m = main[k];
    const base = (b ?? m)!.from;
    const conflict = !!b && !!m && b.to !== m.to;
    return { key: k, label: meta[k]?.label ?? k, unit: meta[k]?.unit ?? null, base, main: m ? m.to : base,
      branch: b ? b.to : base, changedOnBranch: !!b, changedOnMain: !!m, conflict };
  });
}

export function featureText(f: FeatureChange): string {
  if (f.change === "added") return `Added ${f.name}`;
  if (f.change === "removed") return `Removed ${f.name}`;
  const fields = f.fields.filter(x => x !== "id").map(x => (x === "suppressed" ? "suppression" : x.replace(/_/g, " ")));
  return `Edited ${f.name}${fields.length ? ` (${fields.slice(0, 3).join(", ")}${fields.length > 3 ? "…" : ""})` : ""}`;
}

export type Choice = "ours" | "theirs" | "agent";
/** Every conflict needs a choice before merging; "agent" only where the design agent proposed one. */
export function readyToMerge(conflicts: { id: string }[], choices: Record<string, Choice>, proposed: string[]): boolean {
  return conflicts.every(c => choices[c.id] === "ours" || choices[c.id] === "theirs" || (choices[c.id] === "agent" && proposed.includes(c.id)));
}

/** Highlight @mentions of known people in a comment (returns segments for rendering). */
export function mentionSegments(body: string, people: { id: string; name: string }[]): { text: string; mention?: string }[] {
  const names = people.flatMap(p => [p.name, p.name.split(/\s+/)[0]!]).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!names.length) return [{ text: body }];
  const esc = names.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(^|[^\\w@])@(${esc.join("|")})(?!\\w)`, "gi");
  const out: { text: string; mention?: string }[] = [];
  let last = 0;
  for (let m = re.exec(body); m; m = re.exec(body)) {
    const start = m.index + m[1]!.length;
    if (start > last) out.push({ text: body.slice(last, start) });
    out.push({ text: `@${m[2]}`, mention: m[2] });
    last = start + 1 + m[2]!.length;
  }
  if (last < body.length) out.push({ text: body.slice(last) });
  return out;
}
