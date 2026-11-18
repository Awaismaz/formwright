// Drawing depth walkthrough: cosmetic thread UI, thread callout on the sheet, detail view, datum + frame, STEP -> drawing.
import { BASE, start } from "./lib.mjs";

const t = await start();
const { page, api, clickAt, clickText, shot, sleep } = t;
const STEP = process.env.STEP_FILE;

async function sheetPx(rec, x, y) {
  const el = await page.$("[data-testid=sheet-viewer] svg");
  const b = await el.boundingBox();
  return [b.x + x * b.width / rec.sheet.w, b.y + y * b.height / rec.sheet.h];
}
async function viewPx(rec, view, u, v) {
  const vv = rec.sheet.views[view];
  return sheetPx(rec, vv.rect[0] + (u - vv.origin[0]) * vv.scale, vv.rect[1] + (vv.origin[1] - v) * vv.scale);
}
const drawing = async pid => (await api("GET", `/api/m/drawings/projects/${pid}`)).body;
async function waitRec(pid, pred, ms = 90000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { const st = await drawing(pid); if (st?.drawing && pred(st)) return st; await sleep(700); }
  throw new Error("drawing not updated");
}

try {
  console.log("seed", (await api("POST", "/api/god/seed-demo")).status);
  const projects = (await api("GET", "/api/projects")).body?.items ?? [];
  const demo = projects.find(p => /Mounting plate/i.test(p.name)) ?? projects[0];
  const st0 = (await api("GET", `/api/projects/${demo.id}/files/status.json`)).body;
  console.log("demo", demo.name, JSON.stringify(st0.bbox_minmax));
  const [x0, y0, z0, x1, y1, z1] = st0.bbox_minmax;

  // 1) Studio: Hole Wizard with the cosmetic thread toggle, then the Cosmetic Thread command
  await page.goto(`${BASE}/app/projects/${demo.id}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-tour=command-manager]", { timeout: 60000 });
  await sleep(2500);
  await clickAt("::-p-text(Hole Wizard)");
  await sleep(800);
  await clickAt("[aria-label='Hole type'] button:nth-child(2)");
  await sleep(600);
  await page.waitForSelector("[data-testid=thread-toggle] [data-thread-fields]", { timeout: 10000 });
  await shot("01-hole-wizard-thread");
  await page.keyboard.press("Escape");
  await sleep(600);
  await clickAt("::-p-text(Cosmetic Thread)");
  await sleep(800);
  await shot("02-cosmetic-thread-pm");
  await page.keyboard.press("Escape");

  // a tapped M8 hole pattern with its thread, through the same API the PropertyManager uses
  const hole = { op: "hole", name: "M8 Tapped Hole (2×)", point: [x0 + 20, (y0 + y1) / 2, z1], normal: [0, 0, 1], d: 1, depth: 16,
    spec: { type: "tapped", size: 8 }, thread: { size: 8, pitch: 1.25, depth: 12 }, count: 2, step: [x1 - x0 - 40, 0, 0] };
  const add = await api("POST", `/api/projects/${demo.id}/manual`, { feature: hole });
  console.log("add hole", add.status, add.status !== 200 ? JSON.stringify(add.body) : "");
  const st1 = (await api("GET", `/api/projects/${demo.id}/files/status.json`)).body;
  console.log("threads", JSON.stringify(st1.threads?.map(x => [x.designation, x.instances.length])));

  // 2) Drawing Studio: the callout
  await page.goto(`${BASE}/app/modules/drawings?project=${demo.id}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-testid=sheet-viewer] svg", { timeout: 120000 });
  let st = await waitRec(demo.id, s => !s.stale);
  if (st.stale || !(st.drawing.threads ?? []).length) {
    await clickText("Update drawing").catch(() => {});
    st = await waitRec(demo.id, s => (s.drawing.threads ?? []).length > 0);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForSelector("[data-testid=sheet-viewer] svg", { timeout: 60000 });
  }
  console.log("callouts", JSON.stringify(st.drawing.callouts.map(c => c.lines.map(l => l.text))), "chk12", st.drawing.check.passed);
  await sleep(1200);
  await shot("03-sheet-thread-callout");

  // 3) Annotate: detail view around the first tapped hole (picked on the top view)
  await clickAt("[role=tab]::-p-text(Annotate)");
  await sleep(500);
  await shot("04-annotate-tab");
  const rec = st.drawing;
  const th = rec.callouts.find(c => c.lines[0].text.includes("M8"));
  await clickAt("[data-testid=add-detail]");
  await page.waitForSelector("[data-testid=pick-hint]");
  const [hx, hy] = await viewPx(rec, "top", x0 + 20, (y0 + y1) / 2);
  await page.mouse.click(hx, hy);
  st = await waitRec(demo.id, s => (s.drawing.details?.drawn ?? []).length === 1);
  console.log("detail", JSON.stringify(st.drawing.details));
  await sleep(1500);
  await shot("05-detail-view");

  // 4) Datum A picked on the bottom edge of the front view, then a position frame on the tapped holes
  const r2 = st.drawing;
  await page.select("select[aria-label='Datum attached to']", "pick");
  await clickAt("[data-testid=add-datum]");
  await page.waitForSelector("[data-testid=pick-hint]");
  const [dx, dy] = await viewPx(r2, "front", x0 + (x1 - x0) * 0.3, z0);
  await page.mouse.click(dx, dy);
  st = await waitRec(demo.id, s => (s.drawing.gdt?.datums ?? []).length === 1);
  await sleep(800);
  await page.select("select[aria-label='Characteristic']", "position");
  await page.select("select[aria-label='Datum reference 1']", "A");
  await page.select("select[aria-label='Frame attached to']", `callout:${th.id}`);
  await clickAt("[data-testid=add-frame]");
  st = await waitRec(demo.id, s => (s.drawing.gdt?.frames ?? []).length === 1);
  console.log("gdt", JSON.stringify(st.drawing.gdt.frames.map(f => f.text)), JSON.stringify(st.drawing.gdt.datums.map(d => [d.letter, d.view])), "chk12", st.drawing.check.passed, JSON.stringify(st.drawing.check.problems));
  await sleep(1500);
  await shot("06-gdt-on-sheet");

  // 5) STEP -> drawing from the Drawing Studio picker
  await page.goto(`${BASE}/app/modules/drawings`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-testid=step-to-drawing]", { timeout: 30000 });
  await shot("07-picker-step-to-drawing");
  const input = await page.$("[data-testid=step-to-drawing] input[type=file]");
  await input.uploadFile(STEP);
  await page.waitForSelector("[data-testid=inferred-banner]", { timeout: 180000 });
  await page.waitForSelector("[data-testid=sheet-viewer] svg", { timeout: 120000 });
  await sleep(2000);
  const pid2 = new URL(page.url()).searchParams.get("project");
  const st2 = await drawing(pid2);
  console.log("imported", JSON.stringify(st2.drawing.imported), "tags", JSON.stringify([...new Set(st2.drawing.dimensions.map(d => d.tag))]), "chk12", st2.drawing.check.passed);
  await shot("08-step-drawing-inferred");
} catch (e) {
  console.error("FAILED", e);
  await shot("zz-failure").catch(() => {});
  t.problems.push(String(e));
}
await t.finish();
