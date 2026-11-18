// CAD-026 walkthrough: Sheet Metal tab -> Base Flange (sketch) -> Edge Flange x2 + Hem (picked in the viewer) ->
// flat-pattern toggle + tree bend table -> flat DXF -> Drawing Studio flat-pattern sheet -> Manufacturing Advisor.
// Run next to lib.mjs (.claude/skills/studio-e2e/lib.mjs) on a throwaway data dir (see the studio-e2e skill).
import { BASE, start } from "./lib.mjs";

const t = await start();
const { page, api, clickAt, clickText, shot, sleep } = t;
const log = (...a) => console.log(...a);

async function calibrate() {
  const svg = await (await page.$("svg.touch-none")).boundingBox();
  const read = async (x, y) => {
    await page.mouse.move(x, y); await sleep(120);
    const txt = await page.evaluate(() => [...document.querySelectorAll("div")].map(d => d.textContent).find(s => s && /mm · Wheel zoom/.test(s) && s.length < 200));
    const m = /(-?\d+\.\d+), (-?\d+\.\d+) mm/.exec(txt ?? ""); return [Number(m[1]), Number(m[2])];
  };
  const x0 = svg.x + svg.width / 2, y0 = svg.y + svg.height / 2;
  const a = await read(x0, y0), b = await read(x0 + 100, y0 + 100);
  const sx = 100 / (b[0] - a[0]), sy = 100 / (b[1] - a[1]);
  return (u, v) => [x0 + (u - a[0]) * sx, y0 + (v - a[1]) * sy];
}
const status = async pid => (await api("GET", `/api/projects/${pid}/files/status.json`)).body;
const waitPmClosed = async () => { await page.waitForSelector("::-p-text(Add feature)", { hidden: true, timeout: 180000 }); await sleep(2500); };
const pmText = () => page.evaluate(() => document.querySelector("[data-pm-title]")?.closest(".flex.h-full")?.textContent ?? "");
/** Click from the viewer centre in steps along (dx, dy) until the PropertyManager shows a picked line edge. */
async function pickEdge(dx, dy, want) {
  const c = await (await page.$("[data-tour=viewer] canvas")).boundingBox();
  const x0 = c.x + c.width / 2, y0 = c.y + c.height / 2;
  for (let i = 4; i < 200; i++) {
    await page.mouse.click(x0 + dx * i * 2, y0 + dy * i * 2); await sleep(90);
    const txt = await pmText();
    const m = /Line (\d+(?:\.\d+)?) ?mm/.exec(txt);
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

try {
  const pid = (await api("POST", "/api/projects", { name: "Sheet bracket (e2e)" })).body.id;
  await page.goto(`${BASE}/app/projects/${pid}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-tour=command-manager]"); await sleep(1500);
  await clickAt("button::-p-text(Sheet Metal)");
  await sleep(400);
  await shot("01-sheet-metal-tab");
  // 1) Base flange: rectangle 100 x 60 on the Top plane, 2 mm, R2, K 0.44
  await clickAt('button[aria-label="Base Flange"]');
  await clickAt("button[data-plane=Top]"); await sleep(700);
  const px = await calibrate();
  await clickAt('button[aria-label="Corner rectangle"]');
  await page.mouse.click(...px(-50, -30)); await sleep(150); await page.mouse.click(...px(50, 30)); await sleep(300);
  await shot("02-base-flange-sketch");
  await clickText("Exit sketch & create");
  await page.waitForSelector("svg.touch-none", { hidden: true, timeout: 180000 }); await sleep(2500);
  let st = await status(pid);
  log("base", JSON.stringify({ ok: st?.ok, bbox: st?.fingerprint?.bbox, volume: st?.fingerprint?.volume, expect: 100 * 60 * 2, sheet: st?.sheet_metal?.flat }));
  // 2) Edge flange on the back edge (y = +30), 25 mm, material inside
  await clickAt('button[aria-label="Edge Flange"]'); await sleep(500);
  await page.keyboard.down("Control"); await page.keyboard.press("3"); await page.keyboard.up("Control"); await sleep(800);
  log("picked", await pickEdge(0, -1, 100));
  await setField("Flange length", 25);
  await page.keyboard.down("Control"); await page.keyboard.press("1"); await page.keyboard.up("Control"); await sleep(800);
  await shot("03-edge-flange-pm");
  await clickText("Add feature"); await waitPmClosed();
  st = await status(pid);
  const ba = Math.PI / 2 * (2 + 0.44 * 2);
  log("flange1", JSON.stringify({ ok: st?.ok, bbox: st?.fingerprint?.bbox, flat: st?.sheet_metal?.flat?.size, expectY: 60 + 25 - (2 * 4 - ba) }));
  // 3) 45 degree flange, material outside, on the right edge (x = +50, now 56 mm long)
  await clickAt('button[aria-label="Edge Flange"]'); await sleep(500);
  await page.keyboard.down("Control"); await page.keyboard.press("3"); await page.keyboard.up("Control"); await sleep(800);
  log("picked", await pickEdge(1, 0, 56));
  await setField("Flange length", 15); await setField("Flange angle", 45);
  await clickText("Material outside"); await sleep(200);
  await clickText("Add feature"); await waitPmClosed();
  // 4) Hem on the front edge (y = -30)
  await clickAt('button[aria-label="Hem"]'); await sleep(500);
  await page.keyboard.down("Control"); await page.keyboard.press("3"); await page.keyboard.up("Control"); await sleep(800);
  log("picked", await pickEdge(0, 1));
  await setField("Hem length", 8);
  await clickText("Add feature"); await waitPmClosed();
  st = await status(pid);
  log("folded", JSON.stringify({ ok: st?.ok, checks: st?.checks?.filter(c => c.gating).map(c => [c.id, c.passed]), bbox: st?.fingerprint?.bbox,
    flat: st?.sheet_metal?.flat?.size, bends: st?.sheet_metal?.bends?.map(b => [b.name, b.direction, b.angle, b.radius, +b.ba.toFixed(3)]), errors: st?.manual_errors }));
  await page.keyboard.down("Control"); await page.keyboard.press("1"); await page.keyboard.up("Control"); await sleep(1200);
  await shot("04-folded-part-tree");
  // 5) flat pattern toggle (viewer chip) + bend table in the tree
  await clickAt("button[data-flat-toggle]"); await sleep(2500);
  await page.keyboard.down("Control"); await page.keyboard.press("3"); await page.keyboard.up("Control"); await sleep(1200);
  await shot("05-flat-pattern-top");
  await clickAt("button::-p-text(Fold)"); await sleep(1500);
  const dxf = await page.evaluate(async p => { const r = await fetch(`/api/projects/${p}/files/flat.dxf`); const tx = await r.text(); return { status: r.status, cd: r.headers.get("content-disposition"), bendUp: tx.includes("BEND_UP"), bendDown: tx.includes("BEND_DOWN"), bytes: tx.length }; }, pid);
  log("flat.dxf", JSON.stringify(dxf));
  // 6) Drawing Studio: sheet 2 = flat pattern
  await page.goto(`${BASE}/app/modules/drawings?project=${pid}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-testid=sheet-viewer] svg", { timeout: 120000 }); await sleep(1500);
  await shot("06-drawing-sheet1-views");
  await clickAt("button[data-flat-sheet]"); await sleep(2500);
  await shot("07-drawing-sheet2-flat-pattern");
  const drw = (await api("GET", `/api/m/drawings/projects/${pid}`)).body?.drawing;
  log("drawing", JSON.stringify({ chk12: drw?.check?.passed, flat: drw?.flat_pattern && { size: drw.flat_pattern.size, scale: drw.flat_pattern.scale, bends: drw.flat_pattern.bends } }));
  // 7) Manufacturing Advisor: flat size and bend count from the model
  const a = (await api("POST", `/api/m/manufacturing/projects/${pid}/analyse`, { quantity: 10, material: "steel_1018" })).body;
  log("dfm", JSON.stringify({ sheet: a?.signals?.sheet, shm: a?.findings?.filter(f => f.rule.startsWith("SHM")).map(f => [f.rule, f.severity, f.title]) }));
  await page.goto(`${BASE}/app/modules/manufacturing?project=${pid}`, { waitUntil: "domcontentloaded" });
  await sleep(6000);
  await shot("08-manufacturing-advisor");
} catch (e) {
  t.problems.push(`script: ${e.stack ?? e}`);
  await shot("zz-failure").catch(() => {});
}
await t.finish();
