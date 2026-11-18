// Studio follow-ups walkthrough: sheet metal (jog in the UI, closed corner, cut through a bend, flat pattern), the
// agent's multi-step fw-edit (replayed, zero model calls) and the impact gate on tree actions / Ctrl+K commands.
// Run next to lib.mjs (.claude/skills/studio-e2e/lib.mjs) against a throwaway data dir started with
// FW_AGENT_REPLAY=cassette.json (this folder). DATA = that data dir (to read assembly refs).
import fs from "node:fs";
import path from "node:path";
import { BASE, start } from "./lib.mjs";

const t = await start();
const { page, api, clickAt, clickText, shot, sleep, problems } = t;
const log = (...a) => console.log(...a);
await api("PATCH", "/api/god", { enabled: true, bypass_paywall: true, bypass_tokens: true });
const status = async pid => (await api("GET", `/api/projects/${pid}/files/status.json`)).body;
const manual = async (pid, f) => { const r = await api("POST", `/api/projects/${pid}/manual`, { feature: f }); if (r.status !== 200) throw new Error(JSON.stringify(r.body)); };
const waitPmClosed = async () => { await page.waitForSelector("[data-pm-title]", { hidden: true, timeout: 180000 }); await sleep(2500); };
const pmText = () => page.evaluate(() => document.querySelector("[data-pm-title]")?.closest(".flex.h-full")?.textContent ?? "");
async function pickEdge(dx, dy, want) {
  const c = await (await page.$("[data-tour=viewer] canvas")).boundingBox();
  const x0 = c.x + c.width / 2, y0 = c.y + c.height / 2;
  for (let i = 4; i < 220; i++) {
    await page.mouse.click(x0 + dx * i * 2, y0 + dy * i * 2); await sleep(90);
    const m = /Line (\d+(?:\.\d+)?) ?mm/.exec(await pmText());
    if (m && (!want || Math.abs(Number(m[1]) - want) < 0.05)) return Number(m[1]);
  }
  throw new Error(`no edge found towards ${dx},${dy}`);
}
const setField = async (label, value) => {
  const h = await page.evaluateHandle(l => [...document.querySelectorAll("label, div")].find(e => e.textContent?.trim().startsWith(l) && e.querySelector("input"))?.querySelector("input"), label);
  const el = h.asElement(); if (!el) throw new Error(`field ${label}`);
  await el.focus(); await page.keyboard.down("Control"); await page.keyboard.press("a"); await page.keyboard.up("Control");
  await page.keyboard.press("Backspace"); await el.type(String(value));
  await page.evaluate(() => document.activeElement?.blur());
};
const key = async (k, ctrl = true) => { if (ctrl) await page.keyboard.down("Control"); await page.keyboard.press(k); if (ctrl) await page.keyboard.up("Control"); await sleep(700); };
const studio = async pid => { await page.goto(`${BASE}/app/projects/${pid}`, { waitUntil: "domcontentloaded" }); await page.waitForSelector("[data-tour=command-manager]", { timeout: 30000 }); await sleep(3500); };
async function waitBuilt(pid, n = 1, ms = 240000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { const p = await api("GET", `/api/projects/${pid}`); if ((p.body?.builds ?? 0) >= n && !p.body?.agent?.busy) return p.body; await sleep(1000); }
  throw new Error("build timeout " + pid);
}
async function made(name, prompt) {
  const pid = (await api("POST", "/api/projects", { name })).body.id;
  const c = await api("POST", `/api/projects/${pid}/agent/chat`, { prompt, skip_brief: true });
  if (c.status !== 200) throw new Error("chat " + JSON.stringify(c.body));
  await waitBuilt(pid); log("built", name, pid); return pid;
}

const ONLY = process.env.ONLY ?? "ABC";  // run a subset of the parts: ONLY=C
let st;
// ---------------------------------------------------------------- A) sheet metal
if (ONLY.includes("A")) {
const TOP = { origin: [0, 0, 0], normal: [0, 0, 1], x_dir: [1, 0, 0] };
const rect = (x0, y0, x1, y1) => { const p = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]; return { kind: "loop", segs: p.map((a, i) => ({ type: "line", a, b: p[(i + 1) % 4] })) }; };
const sid = (await api("POST", "/api/projects", { name: "Sheet tray (e2e)" })).body.id;
await manual(sid, { op: "sm_base", name: "Base-Flange1", plane: TOP, profiles: [rect(-50, -30, 50, 30)], t: 2, r: 2, k: 0.44,
  relief: { type: "rect", ratio: 0.5 }, corner: { type: "closed", gap: 0.5 } });
await studio(sid);
// jog on the left end, picked in the viewer: 20 mm in from the edge, raised 10 mm
await clickAt("button::-p-text(Sheet Metal)"); await sleep(400);
await clickAt('button[aria-label="Jog"]'); await sleep(500);
await key("3");
log("jog edge", await pickEdge(-1, 0, 60));
await setField("Jog line distance from the edge", 20); await setField("Jog offset", 10);
await key("1");
await shot("01-jog-propertymanager");
await clickText("Add feature"); await waitPmClosed();
st = await status(sid);
const ba = Math.PI / 2 * (2 + 0.44 * 2), m = 10 - (2 + 4);
log("jog", JSON.stringify({ ok: st.ok, bbox: st.fingerprint.bbox, flat: st.sheet_metal.flat.size, expect: [100 + 2 * ba + m, 60] }));
// flanges on the back and right edges of the staying piece: they meet at a closed corner (relief cut automatically)
await manual(sid, { op: "sm_flange", name: "Edge-Flange1", edge: [10, 30, 2], edge_ref: { kind: "line", dir: [1, 0, 0] }, length: 20, angle: 90, inset: [0, 5] });
await manual(sid, { op: "sm_flange", name: "Edge-Flange2", edge: [50, 0, 2], edge_ref: { kind: "line", dir: [0, 1, 0] }, length: 20, angle: 90 });
// a 10 x 10 window cut through the back flange's bend
await manual(sid, { op: "extrude", name: "Bend window", plane: { origin: [10, 30, 4], normal: [0, 1, 0] }, sketch: { kind: "rect", w: 10, h: 10, cx: 0, cy: 0 }, distance: 6, mode: "cut" });
st = await status(sid);
log("tray", JSON.stringify({ ok: st.ok, errors: st.manual_errors, bends: st.sheet_metal.bend_count, corner: st.sheet_metal.corner, notes: st.sheet_metal.notes, flat: st.sheet_metal.flat }));
await studio(sid);
await key("1"); await sleep(800);
await shot("02-closed-corner-jog-window-folded");
await clickAt("::-p-text(Flat-Pattern)").catch(() => log("no flat toggle text"));
await sleep(3500); await key("3"); await sleep(1500);
await shot("03-flat-pattern-relief-window-jog");
await clickAt("::-p-text(Flat-Pattern)").catch(() => {}); await sleep(2000);
// edit the base flange: the sketch editor shows the corner settings
await clickText("Base-Flange1"); await sleep(3000);
await shot("04-base-flange-corner-settings");
await clickText("Cancel").catch(() => page.keyboard.press("Escape")); await sleep(1000);

}
// ---------------------------------------------------------------- B) agent: several edits in one block
if (ONLY.includes("B")) {
const box = await made("Pocket box", "Build the pocket box");
await studio(box);
const send = async text => {
  const ta = await page.waitForSelector("textarea", { visible: true });
  await ta.click({ clickCount: 3 }); await ta.type(text); await key("Enter");
};
await send("make the pockets 5 deep and four of them, 12 apart");
await page.waitForSelector("[data-testid=edit-steps]", { timeout: 60000 });
// a fresh suggestion opens by itself; if the event stream reconnected meanwhile it is history, so use the card's button
if (!(await page.waitForSelector("[data-agent-edit]", { timeout: 15000 }).catch(() => null))) {
  log("auto-open missed: opening from the card"); await clickText("Open step 1 of 2");
  await page.waitForSelector("[data-agent-edit]", { timeout: 30000 });
}
await sleep(1200);
await shot("05-agent-multi-edit-step1-extrude-pm");
await waitBuilt(box);  // OK is refused while the agent's turn is still finishing
await clickText("Update feature"); await page.waitForFunction(() => /Step 2 of 2/.test(document.querySelector("[data-agent-edit]")?.textContent ?? ""), { timeout: 180000 });
await sleep(1500);
await shot("06-step2-pattern-pm-prefilled");
await clickText("Update feature"); await waitPmClosed();
st = await status(box);
log("multi", JSON.stringify({ ok: st.ok, volume: st.fingerprint.volume, expect: 24000 - 4 * 6 * 6 * 5 - 2 * Math.PI * 4 * 10 }));
await shot("07-multi-edit-applied");

}
// ---------------------------------------------------------------- C) impact gate on tree actions and Ctrl+K
if (ONLY.includes("C")) {
const plate = await made("Base plate", "Build the base plate");
const pin = await made("Pin", "Build the pin");
let v = (await api("POST", "/api/m/assembly/assemblies", { project_id: plate })).body;
const aid = v.assembly.id, pI = v.instances[0].id;
const nI = (await api("POST", `/api/m/assembly/assemblies/${aid}/instances`, { project_id: pin })).body.result.instance;
await api("PATCH", `/api/m/assembly/assemblies/${aid}/instances/${nI}`, { T: [1, 0, 0, 50, 0, 1, 0, 30, 0, 0, 1, 5] });
v = (await api("GET", `/api/m/assembly/assemblies/${aid}`)).body;
const me = (await api("GET", "/api/auth/me")).body;
const refs = iid => JSON.parse(fs.readFileSync(path.join(process.env.DATA, "assemblies", me.org.id, "_parts", v.instances.find(i => i.id === iid).part, "refs.json"), "utf8"));
const axis = (iid, x, y, r) => Number(Object.entries(refs(iid).faces).find(([, f]) => f.kind === "axis" && Math.abs(f.r - r) < 1e-6 && Math.abs(f.p[0] - x) < 1e-6 && Math.abs(f.p[1] - y) < 1e-6)[0]);
log("mate", (await api("POST", `/api/m/assembly/assemblies/${aid}/mates`, { type: "concentric", a: { inst: pI, kind: "face", id: axis(pI, 50, 30, 3.3) }, b: { inst: nI, kind: "face", id: axis(nI, 0, 0, 3) } })).status);
await studio(plate);
// seen once right after a replayed build: the tree loaded before its feature list; a reload shows it
if (!(await page.waitForSelector('button[aria-label="Suppress Pin hole"]', { timeout: 20000 }).catch(() => null))) {
  log("tree empty on first load: reloading"); await studio(plate);
  await page.waitForSelector('button[aria-label="Suppress Pin hole"]', { timeout: 30000 });
}
await sleep(1500);
await page.click('button[aria-label="Suppress Pin hole"]');
await page.waitForSelector("[data-testid=impact-panel]", { timeout: 180000 }); await sleep(600);
await shot("08-tree-suppress-impact-gate");
await clickText("Back"); await sleep(800);
await key("k");
await page.keyboard.type("move"); await sleep(200);
await page.keyboard.press("Escape"); await sleep(400);
await key("k");
await page.keyboard.type("suppress Pin hole"); await sleep(400);
await shot("09-ctrl-k-suppress-command");
await page.keyboard.press("Enter");
await page.waitForSelector("[data-testid=impact-panel]", { timeout: 180000 }); await sleep(600);
await shot("10-ctrl-k-impact-gate");
await clickText("Apply anyway");
await sleep(6000);
const feats = (await api("GET", `/api/projects/${plate}/manual`)).body.features;
log("after apply", JSON.stringify(feats.map(f => [f.name, f.suppressed])));
await shot("11-applied-after-gate");
}
log("problems", problems.length);
await t.finish();
