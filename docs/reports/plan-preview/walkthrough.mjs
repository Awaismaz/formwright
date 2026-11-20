// Plan preview walkthrough (WORKLIST 47) on 8815: simulated agents, intent replies replayed.
import fs from "node:fs";
import { start, BASE, OUT } from "./lib.mjs";

const { page, api, clickAt, shot, sleep, problems, finish } = await start();
const numbers = {};
const log = (k, v) => { numbers[k] = v; console.log(k, JSON.stringify(v)); };

async function newProgram(name, brief) {
  const r = await api("POST", "/api/office/programs", { name, brief, planner: "archie", deliverables: false });
  if (r.status !== 200) throw new Error(`create ${r.status} ${JSON.stringify(r.body)}`);
  const pid = r.body.id;
  for (let i = 0; i < 120; i++) {
    const v = await api("GET", `/api/office/programs/${pid}`);
    if (v.body?.status === "plan_review") return pid;
    await sleep(500);
  }
  throw new Error("no plan review for " + name);
}

async function timeEndpoint(pid, n = 5) {
  return page.evaluate(async (pid, n) => {
    const out = [];
    for (let i = 0; i < n; i++) {
      const t0 = performance.now();
      const r = await fetch(`/api/office/programs/${pid}/preview`, { credentials: "same-origin" });
      const j = await r.json();
      out.push({ wall: Math.round(performance.now() - t0), server: j.ms?.total, bodies: j.bodies?.length, bytes: JSON.stringify(j).length });
    }
    return out;
  }, pid, n);
}

async function openProgram(pid, tab) {
  await page.goto(`${BASE}/app/office/programs/${pid}${tab ? `?tab=${tab}` : ""}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-plan-preview][data-render-ms]", { timeout: 30000 });
  await sleep(600);
}
const previewState = sel => page.$eval(sel ?? "[data-plan-preview]", el => ({
  render: Number(el.getAttribute("data-render-ms")), server: Number(el.getAttribute("data-server-ms")), errors: Number(el.getAttribute("data-errors")),
  dims: el.querySelectorAll("[data-preview-dim]").length, issues: el.querySelectorAll("[data-preview-issue]").length,
  title: el.querySelector("span.font-semibold")?.textContent }));

// 1. A plan with a question: the preview is there at once
const pair = await newProgram("Pair", "A 1:2 spur pair m2 20/40 on two shafts with 6204 bearings");
const t0 = Date.now();
await openProgram(pair);
log("pair_page_to_preview_ms", Date.now() - t0);
log("pair_before", await previewState());
await shot("1-plan-review-preview");

// 2. hover the Pinion row: its body lights up and its size shows
const row = await page.$$eval("[data-plan-row]", els => els.map(e => [e.getAttribute("data-plan-row"), e.querySelector("input")?.value]));
const pin = row.find(r => r[1] === "Pinion");
await page.setViewport({ width: 1600, height: 2000 });
await page.evaluate(() => window.scrollTo(0, 0));
await sleep(500);
const rb = await (await page.$(`[data-plan-row="${pin[0]}"]`)).boundingBox();
await page.mouse.move(rb.x + 60, rb.y + rb.height / 2);
await sleep(500);
log("hover_row_dims", await page.$$eval("[data-preview-dim]", els => els.map(e => e.textContent)));
await shot("2-hover-pinion-row");
await page.mouse.move(5, 5);
await page.setViewport({ width: 1600, height: 1000 });
await sleep(400);

// 3. click the centre distance: where the number came from
const cd = await page.$("[data-preview-dim^='cd:']");
await cd.click();
await sleep(300);
log("cd_source", await page.$eval("[data-dim-source]", el => el.textContent));
await shot("3-centre-distance-source");
await cd.click();

// 4. hover a part in the 3D view: its plan row highlights
const canvas = await page.$("[data-plan-preview] canvas");
const cb = await canvas.boundingBox();
let hotRow = null;
for (const [fx, fy] of [[0.5, 0.5], [0.45, 0.5], [0.55, 0.5], [0.4, 0.45], [0.6, 0.55], [0.5, 0.4]]) {
  await page.mouse.move(cb.x + cb.width * fx, cb.y + cb.height * fy);
  await sleep(250);
  hotRow = await page.$eval("[data-hot='1']", e => e.querySelector("input")?.value).catch(() => null);
  if (hotRow) break;
}
log("hover_body_row", hotRow);
await shot("4-hover-body-row");
await page.mouse.move(5, 5);

// 5. answer Archie's question: the preview updates (housing, caps; the caps conflict in red)
await clickAt("::-p-text(A split housing with bearing caps)");
await clickAt("::-p-text(Apply my answers)");
const tA = Date.now();
await page.waitForFunction(() => Number(document.querySelector("[data-plan-preview]")?.getAttribute("data-errors")) > 0, { timeout: 30000 });
log("answer_to_updated_preview_ms", Date.now() - tA);
await sleep(800);
log("pair_after_answer", await previewState());
log("issue_texts", await page.$$eval("[data-preview-issue]", els => els.map(e => e.textContent.slice(0, 140))));
await page.$eval("[data-plan-preview]", el => el.scrollIntoView({ block: "center" }));
await sleep(300);
await shot("5-answered-conflict-red");
// hover the first problem: its parts are highlighted
const iss = await page.$("[data-preview-issue]");
const ib = await iss.boundingBox();
await page.mouse.move(ib.x + 30, ib.y + 6);
await sleep(300);
await shot("6-problem-hovered");
await page.mouse.move(5, 5);

// 6. edit the plan: the preview shows the edits before saving
const coverRow = (await page.$$eval("[data-plan-row]", els => els.map(e => e.querySelector("input")?.value))).indexOf("Housing cover");
const trash = await page.$$("button[aria-label='Remove Housing cover']");
if (trash.length) {
  await trash[0].click();
  await page.waitForFunction(() => document.querySelector("[data-plan-preview] span.font-semibold")?.textContent?.includes("your edits"), { timeout: 15000 });
  await sleep(1200);
  log("edited", { coverRow, ...(await previewState()) });
  await page.$eval("[data-plan-preview]", el => el.scrollIntoView({ block: "center" }));
  await shot("7-edited-plan-preview");
}

// 7. timing: the reducer and the table
for (const [key, name, brief] of [["reducer", "Gear Reducer", "Build a Single stage 3:1 reducer with Spur Gears"], ["table", "TEST Project", "Design a foldable Table"]]) {
  const pid = await newProgram(name, brief);
  log(`${key}_endpoint`, await timeEndpoint(pid));
  const tP = Date.now();
  await openProgram(pid);
  log(`${key}_page_to_preview_ms`, Date.now() - tP);
  log(`${key}_preview`, await previewState());
  await page.$eval("[data-plan-preview]", el => el.scrollIntoView({ block: "center" }));
  await sleep(300);
  await shot(`8-${key}-preview`);
  numbers[`${key}_pid`] = pid;
}

// 8. the interfaces gate: approve the reducer's plan, the Interfaces tab shows the same layout
const red = numbers.reducer_pid;
let r = await api("POST", `/api/office/programs/${red}/gates/brief/approve`, {});
log("reducer_brief_approve", r.status);
await openProgram(red, "interfaces");
await page.$eval("[data-plan-preview]", el => el.scrollIntoView({ block: "center" }));
await sleep(400);
log("reducer_icd_preview", await previewState());
await shot("9-interfaces-gate-preview");
// select another interface: its two sides light up
const rows = await page.$$("[data-icd-row]");
if (rows.length > 2) { await rows[2].click(); await sleep(400); await page.$eval("[data-plan-preview]", el => el.scrollIntoView({ block: "center" })); await shot("10-interface-selected"); }

// 9. a program revision, before and after
const tab = numbers.table_pid;
r = await api("POST", `/api/office/programs/${tab}/gates/brief/approve`, {});
log("table_brief", [r.status, r.body?.detail]);
r = await api("GET", `/api/office/programs/${tab}`);
log("table_icd_problems", r.body?.icd?.problems);
r = await api("POST", `/api/office/programs/${tab}/gates/icd/approve`, {});
log("table_icd_approve", [r.status, r.body?.detail]);
r = await api("POST", `/api/office/programs/${tab}/revision`, { changes: [{ op: "qty", part: "Folding leg", qty: 2 }, { op: "qty", part: "Leg hinge bracket", qty: 2 }], reason: "two legs" });
log("table_revision", [r.status, r.body?.revision?.id ?? r.body?.detail]);
await page.goto(`${BASE}/app/office/programs/${tab}?tab=archie`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-compare-open]", { timeout: 30000 });
await clickAt("[data-compare-open]");
await page.waitForSelector("[data-revision-compare] [data-plan-preview='after'][data-render-ms]", { timeout: 30000 });
await sleep(900);
log("compare_badges", await page.$eval("[data-revision-compare]", el => el.querySelector("div")?.textContent));
await shot("11-revision-before-after");

fs.writeFileSync(`${OUT}/numbers.json`, JSON.stringify(numbers, null, 1));
console.log("problems", problems);
await finish();
