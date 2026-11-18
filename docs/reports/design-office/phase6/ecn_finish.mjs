// Second half of office6_walkthrough.mjs after ECN-001 was raised: the engineer approves parts Gage escalated (a
// simulated designer can't act on "+2 mm" in a reason) or that wait for review, then releases Rev B and checks that the
// Rev A pack is byte-identical. Same environment as office6_walkthrough.mjs.
import crypto from "node:crypto";
import { start } from "./lib.mjs";

const { page, api, clickAt, shot, sleep, problems, finish } = await start();
const URL = process.env.FW_URL;
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const l = (await api("GET", "/api/office/programs")).body;
const pid = (l.items ?? l).find(x => x.name === "Gearbox GB-6").id;
const prog = async () => (await api("GET", `/api/office/programs/${pid}`)).body;
const packA = async () => { const b = await page.evaluate(async u => Array.from(new Uint8Array(await (await fetch(u)).arrayBuffer())),
  `/api/office/programs/${pid}/releases/A/pack.zip`); return crypto.createHash("sha256").update(Buffer.from(b)).digest("hex"); };
const hashA = await packA();
log("Rev A pack sha256", hashA.slice(0, 16));
let v;
log("run", (await api("POST", `/api/office/programs/${pid}/run`)).status);
for (let k = 0; k < 600; k++) {
  v = await prog();
  for (const t of v.tickets) {
    const st = t.run?.status ?? t.run_status;
    if (st === "awaiting_review") log("review", t.title, (await api("POST", `/api/office/programs/${pid}/tickets/${t.id}/review`, { decision: "approve" })).status);
    else if (st === "blocked" && t.kind === "part" && t.column === "changes_requested") log("engineer approves", t.title, (await api("POST", `/api/office/programs/${pid}/tickets/${t.id}/move`, { column: "approved" })).status);
  }
  if ((v.ecns ?? []).some(e => e.status === "ready")) break;
  await sleep(2000);
}
log("ECN", JSON.stringify((v.ecns ?? []).map(e => [e.id, e.status])));
const r = await api("POST", `/api/office/programs/${pid}/release`, { note: "ECN-001" });
log("release B", r.status, r.status !== 200 ? JSON.stringify(r.body).slice(0, 300) : "");
v = await prog();
log("released", v.released?.rev, "parts", JSON.stringify((v.releases ?? []).at(-1)?.diff?.parts?.map?.(p => `${p.title} ${p.from ?? ""}->${p.to ?? p.rev}`) ?? []).slice(0, 300));
log("Rev A pack unchanged:", (await packA()) === hashA);
await page.goto(`${URL}/app/office/programs/${pid}`, { waitUntil: "domcontentloaded" });
await sleep(2500);
await clickAt('button[role=tab][id$="-trigger-deliverables"]');
await sleep(2000);
await shot("ecn_02_rev_b_released");
await page.evaluate(() => document.querySelector("[data-ecn-log]")?.scrollIntoView());
await sleep(800);
await shot("ecn_03_ecn_log");
log("problems", problems.length);
await finish();
