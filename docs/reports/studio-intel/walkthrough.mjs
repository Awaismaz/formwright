import fs from "node:fs";
import path from "node:path";
import { start } from "./lib.mjs";

const DATA = process.env.DATA;
const { page, api, clickAt, shot, sleep, finish, problems } = await start();
const log = (...a) => console.log(...a);
await api("PATCH", "/api/god", { enabled: true, bypass_paywall: true, bypass_tokens: true });

async function waitBuilt(pid, n = 1, ms = 240000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const p = await api("GET", `/api/projects/${pid}`);
    if ((p.body?.builds ?? 0) >= n && !p.body?.agent?.busy) return p.body;
    await sleep(1000);
  }
  throw new Error("build timeout " + pid);
}
async function made(name, prompt) {
  const r = await api("POST", "/api/projects", { name });
  const pid = r.body.id;
  const c = await api("POST", `/api/projects/${pid}/agent/chat`, { prompt, skip_brief: true });
  if (c.status !== 200) throw new Error("chat " + JSON.stringify(c.body));
  await waitBuilt(pid);
  log("built", name, pid);
  return pid;
}
const plate = await made("Base plate", "Build the base plate");
const block = await made("Block", "Build the block");
const pin = await made("Pin", "Build the pin");

// assembly: plate fixed, block on its top face, pin concentric with the (50, 30) hole
let v = (await api("POST", "/api/m/assembly/assemblies", { project_id: plate })).body;
const aid = v.assembly.id, pI = v.instances[0].id;
const bI = (await api("POST", `/api/m/assembly/assemblies/${aid}/instances`, { project_id: block })).body.result.instance;
const nI = (await api("POST", `/api/m/assembly/assemblies/${aid}/instances`, { project_id: pin })).body.result.instance;
const T = (x, y, z) => [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z];
await api("PATCH", `/api/m/assembly/assemblies/${aid}/instances/${bI}`, { T: T(0, 0, 10) });
await api("PATCH", `/api/m/assembly/assemblies/${aid}/instances/${nI}`, { T: T(50, 30, 5) });
v = (await api("GET", `/api/m/assembly/assemblies/${aid}`)).body;
const me = (await api("GET", "/api/auth/me")).body;
const refs = iid => { const inst = v.instances.find(i => i.id === iid); return JSON.parse(fs.readFileSync(path.join(DATA, "assemblies", me.org.id, "_parts", inst.part, "refs.json"), "utf8")); };
const plane = (iid, nz, z) => Number(Object.entries(refs(iid).faces).find(([, f]) => f.kind === "plane" && Math.abs(f.v[2] - nz) < 1e-9 && Math.abs(f.p[2] - z) < 1e-9)[0]);
const axis = (iid, x, y, r) => Number(Object.entries(refs(iid).faces).find(([, f]) => f.kind === "axis" && Math.abs(f.r - r) < 1e-6 && Math.abs(f.p[0] - x) < 1e-6 && Math.abs(f.p[1] - y) < 1e-6)[0]);
let m = await api("POST", `/api/m/assembly/assemblies/${aid}/mates`, { type: "coincident", a: { inst: pI, kind: "face", id: plane(pI, 1, 10) }, b: { inst: bI, kind: "face", id: plane(bI, -1, 0) } });
log("mate1", m.status);
m = await api("POST", `/api/m/assembly/assemblies/${aid}/mates`, { type: "concentric", a: { inst: pI, kind: "face", id: axis(pI, 50, 30, 3.3) }, b: { inst: nI, kind: "face", id: axis(nI, 0, 0, 3) } });
log("mate2", m.status);
// a datasheet shot for the plate (never rendered: stale)
const sh = await api("POST", `/api/m/mesh/projects/${plate}/shots`, { finish: "clay", quality: "final" });
log("shot", sh.status, sh.body?.stale);

// --- Studio of the plate
await page.goto(`${process.env.FW_URL}/app/projects/${plate}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-tour=command-manager]", { timeout: 30000 });
await sleep(4000);
await shot("01-studio-where-used-datasheet-chip");
const send = async text => {
  const ta = await page.waitForSelector("textarea", { visible: true });
  await ta.click({ clickCount: 3 }); await ta.type(text); await page.keyboard.down("Control"); await page.keyboard.press("Enter"); await page.keyboard.up("Control");
};
// 1) agent parameter edit -> Modify dimensions PM + impact in the chat card
await send("remove the mounting holes");
await page.waitForSelector("[data-testid=param-pm]", { timeout: 60000 });
await page.waitForSelector("[data-testid=edit-card] [data-testid=impact-details]", { timeout: 120000 });
await sleep(800);
await shot("02-agent-param-edit-pm-and-chat-impact");
await clickAt("[data-testid=param-pm] button[aria-label=OK]");
await page.waitForSelector("[data-testid=impact-panel]", { timeout: 120000 });
await sleep(500);
await shot("03-impact-panel-before-apply");
await clickAt("::-p-text(Back)");
await clickAt("[data-testid=param-pm] button[aria-label=Cancel]");
await sleep(500);
// 2) agent chamfer -> real PropertyManager pre-filled, edges highlighted
await send("chamfer the top edges 1 mm");
await page.waitForSelector("[data-agent-edit]", { timeout: 60000 });
await sleep(1500);
await shot("04-agent-chamfer-pm-prefilled-highlighted");
await clickAt("button[aria-label=OK]");
await page.waitForSelector("[data-agent-edit]", { hidden: true, timeout: 180000 });
await sleep(3000);
await shot("05-chamfer-applied-after-impact-check");
const man = await api("GET", `/api/projects/${plate}/manual`);
log("manual features", JSON.stringify(man.body.features.map(f => [f.op, f.d, f.edges?.length])));
const st = await api("GET", `/api/projects/${plate}/files/status.json`);
log("status ok", st.body?.ok, "volume", st.body?.fingerprint?.volume);
await page.waitForSelector("[data-testid=datasheet-chip]", { timeout: 20000 }).catch(() => log("no datasheet chip"));
await shot("06-after-revision");
// Mesh Studio datasheet tab
await page.goto(`${process.env.FW_URL}/app/modules/mesh?project=${plate}`, { waitUntil: "domcontentloaded" });
await sleep(6000);
await clickAt("::-p-text(Datasheet)").catch(e => log("no datasheet tab", e.message));
await sleep(1500);
await shot("07-mesh-datasheet-pack");
log("problems", problems.length);
await finish();
