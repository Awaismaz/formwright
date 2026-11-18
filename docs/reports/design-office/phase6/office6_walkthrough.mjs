// Design Office Phase 6 walkthrough (throwaway data, simulated agents): gearbox layout with shafts in the side walls,
// per-part review gate, motion check on the program assembly, release Rev A, change notice -> Rev B.
// Run next to lib.mjs from .claude/skills/studio-e2e (see that skill), server started with FW_OFFICE_FAKE_AGENTS=1.
import crypto from "node:crypto";
import { start } from "./lib.mjs";

const { page, api, clickAt, shot, sleep, problems, finish } = await start();
const URL = process.env.FW_URL;
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const prog = async pid => (await api("GET", `/api/office/programs/${pid}`)).body;
const waitFor = async (pid, pred, what, secs = 1800) => {
  for (let k = 0; k < secs / 2; k++) { const v = await prog(pid); if (pred(v)) return v; await sleep(2000); }
  throw new Error(`timed out: ${what}`);
};
const tab = async name => { await clickAt(`button[role=tab][id$="-trigger-${name}"]`); await sleep(1500); };
const open = async pid => { await page.goto(`${URL}/app/office/programs/${pid}`, { waitUntil: "domcontentloaded" }); await sleep(2500); };

let r, v, pid;
if (!process.env.PID) {
// ---- program with the review gate on
r = await api("POST", "/api/office/programs", { name: "Gearbox GB-6", brief: "A spur gear reducer, 3:1, 1450 rpm input, for a conveyor drive.",
  planner: "standard", review_gate: true });
if (r.status !== 200) throw new Error(JSON.stringify(r));
pid = r.body.id;
r = await api("POST", `/api/office/programs/${pid}/gates/brief/approve`, {});
log("brief", r.status);
v = await prog(pid);
log("ICD", v.icd.interfaces.length, "interfaces:", v.icd.interfaces.map(f => `${f.id} ${f.kind}${f.data.ax ? "/" + f.data.ax : ""}`).join(", "));
log("notes", JSON.stringify(v.skeleton?.notes ?? []));
await open(pid);
await tab("interfaces");
await clickAt('[data-icd-row="IF-02"]');
await sleep(800);
await shot("layout_01_icd_bearing_seat_side_walls");
await clickAt('[data-icd-row="IF-07"]');
await sleep(800);
await shot("layout_02_icd_cap_over_seat");
r = await api("POST", `/api/office/programs/${pid}/gates/icd/approve`, {});
log("icd approve", r.status);
v = await waitFor(pid, v => v.assembly?.status && v.assembly.status !== "building", "placeholder assembly", 600);
log("placeholders:", v.assembly.summary);
await open(pid);
await tab("assembly");
await sleep(6000);
await shot("layout_03_placeholders");

// ---- run: parts stop for review
r = await api("POST", `/api/office/programs/${pid}/run`);
log("run", r.status);
v = await waitFor(pid, v => v.tickets.some(t => t.run_status === "awaiting_review"), "first review", 1200);
const first = v.tickets.find(t => t.run_status === "awaiting_review");
log("waiting for review:", first.title);
await open(pid);
await sleep(1500);
await shot("review_01_board_waiting");
await clickAt(`[aria-label*="${first.key} "]`);
await page.waitForSelector("[data-review-gate]", { timeout: 20000 });
await sleep(800);
await shot("review_02_drawer");
await page.type("[data-review-gate] textarea", "Break the outer edges 0.5 x 45° before release.");
await clickAt("::-p-text(Request changes)");
await sleep(2500);
await shot("review_03_changes_requested");
await page.keyboard.press("Escape");
// approve everything that waits (the changed part comes back to review once more)
const t0 = Date.now();
for (let k = 0; k < 900; k++) {
  v = await prog(pid);
  if (v.orchestrator?.state === "complete") break;  // after Ortho and Smithy too
  for (const t of v.tickets.filter(t => t.run_status === "awaiting_review")) {
    const a = await api("POST", `/api/office/programs/${pid}/tickets/${t.id}/review`, { decision: "approve" });
    log("approved", t.title, a.status);
  }
  await sleep(2000);
}
log("program", v.status, "in", Math.round((Date.now() - t0) / 1000), "s;", v.assembly?.summary);
} else {
  pid = process.env.PID;
  if (pid === "auto") { const l = (await api("GET", "/api/office/programs")).body; pid = (l.programs ?? l.items ?? l).find(x => x.name === "Gearbox GB-6").id; }
  // a deliverable blocked before a fix: retry it, and make sure the office runs
  v = await prog(pid);
  for (const t of v.tickets.filter(t => t.kind === "deliverable" && t.column !== "approved"))
    log("retry", t.title, (await api("POST", `/api/office/programs/${pid}/tickets/${t.id}/control`, { action: "retry" })).status);
  log("run", (await api("POST", `/api/office/programs/${pid}/run`)).status);
  v = await waitFor(pid, v => v.orchestrator?.state === "complete", "deliverables", 1200); }
await open(pid);
await tab("assembly");
await sleep(8000);
await shot("layout_04_final_assembly");

// ---- motion on the horizontal gearbox
const tm = Date.now();
await clickAt("[data-check-motion]");
await page.waitForSelector("[data-program-motion] [data-motion-summary]", { timeout: 1200000 });
log("motion", (Date.now() - tm) / 1000, "s:", await page.$eval("[data-program-motion] [data-motion-summary]", e => e.textContent));
await sleep(1500);
await shot("motion_05_gearbox_horizontal");

// ---- release Rev A, ECN-001 on the output gear -> Rev B
r = await api("POST", `/api/office/programs/${pid}/release`);
log("release A", r.status, r.status !== 200 ? JSON.stringify(r.body).slice(0, 300) : r.body?.release?.rev ?? "");
if (r.status !== 200) throw new Error("release A failed");
const packA = async () => { const res = await page.evaluate(async u => { const b = await (await fetch(u)).arrayBuffer(); return Array.from(new Uint8Array(b)); },
  `/api/office/programs/${pid}/releases/A/pack.zip`); return crypto.createHash("sha256").update(Buffer.from(res)).digest("hex"); };
const hashA = await packA();
log("Rev A pack sha256", hashA.slice(0, 16));
v = await prog(pid);
const gear = v.tickets.find(t => t.title === "Output gear");
r = await api("POST", `/api/office/programs/${pid}/ecn`, { reason: "Output gear face width +2 mm for a longer service life.", items: [gear.item_id] });
log("ECN", r.status, r.body?.ecn?.id, r.body?.ecn?.titles ?? r.body?.detail);
if (r.status !== 200) throw new Error("ECN failed");
await open(pid);
await tab("deliverables");
await shot("ecn_01_in_work");
for (let k = 0; k < 900; k++) {
  v = await prog(pid);
  for (const t of v.tickets.filter(t => t.run_status === "awaiting_review")) await api("POST", `/api/office/programs/${pid}/tickets/${t.id}/review`, { decision: "approve" });
  if ((v.ecns ?? []).some(e => e.status === "ready")) break;
  await sleep(2000);
}
r = await api("POST", `/api/office/programs/${pid}/release`);
log("release B", r.status, r.status !== 200 ? JSON.stringify(r.body).slice(0, 300) : "");
v = await prog(pid);
log("released", JSON.stringify(v.released ?? {}).slice(0, 200));
log("Rev A pack unchanged:", (await packA()) === hashA);
await open(pid);
await tab("deliverables");
await sleep(1500);
await shot("ecn_02_rev_b_released");
await page.evaluate(() => document.querySelector("[data-ecn-log]")?.scrollIntoView());
await sleep(800);
await shot("ecn_03_ecn_log");
log("problems", problems.length);
await finish();
