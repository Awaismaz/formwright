// Viewport dimensions walkthrough: toggle on (D), hover highlight (faces + Params row), edit a length on screen,
// rebuilt + dimension updated, undo (Ctrl+Z), then the flange (count, PCD), the shaft and a Toolbox part.
import { BASE, start } from "./lib.mjs";

const t = await start();
const { page, api, clickAt, clickText, shot, sleep } = t;
const status = async pid => (await api("GET", `/api/projects/${pid}/files/status.json`)).body;
const dimTexts = () => page.$$eval("[data-dim]", els => els.map(e => `${e.getAttribute("data-dim")}=${e.textContent}`));
const waitDims = async (min = 1, timeout = 120000) => {
  const t0 = Date.now();
  await page.waitForFunction(n => document.querySelectorAll("[data-dim]").length >= n, { timeout }, min);
  return (Date.now() - t0) / 1000;
};
const waitBuildChange = async (pid, from, timeout = 120000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) { const s = await status(pid); if (s?.build_id && s.build_id !== from) return s; await sleep(400); }
  throw new Error("no rebuild");
};
const open = async pid => {
  await page.goto(`${BASE}/app/projects/${pid}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-tour=command-manager]", { timeout: 120000 }); await sleep(2500);
};
const hoverOn = async sel => { const el = await page.waitForSelector(sel, { visible: true }); const b = await el.boundingBox(); await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2); await sleep(400); };

try {
  const have = (await api("GET", "/api/projects")).body;
  const seed = (have.items ?? have).length ? { status: "kept" } : await api("POST", "/api/god/seed-demo");
  console.log("seed-demo", seed.status);
  const projects = (await api("GET", "/api/projects")).body.items ?? (await api("GET", "/api/projects")).body;
  const find = re => projects.find(p => re.test(p.name));
  const plate = find(/mounting plate/i), flange = find(/flange/i), shaft = find(/shaft/i);
  console.log("projects", projects.map(p => p.name).join(" | "));

  // ---- mounting plate: toggle on with the keyboard
  await open(plate.id);
  await clickAt('button[title="Params"]').catch(() => clickText("Params"));
  await sleep(500);
  await page.mouse.move(800, 500);
  await page.keyboard.press("d");
  const tMap = await waitDims(5);
  await sleep(800);
  const dimsApi = (await api("GET", `/api/projects/${plate.id}/dims`)).body;
  console.log("plate dims shown after", tMap, "s; server", JSON.stringify(dimsApi.timings), "state", dimsApi.state);
  console.log("labels", (await dimTexts()).join(", "));
  await shot("01-plate-dims-on");

  // ---- hover a dimension: faces + Params row
  await hoverOn("[data-dim=L]");
  const rowHot = await page.$eval("[data-param-row=L]", e => e.className.includes("border-primary"));
  console.log("hover L -> Params row highlighted:", rowHot);
  await shot("02-hover-length");
  // ---- and the other way: a Params row highlights its dimension
  await hoverOn("[data-param-row=HOLE_D]");
  const dimHot = await page.$eval("[data-dim=HOLE_D]", e => e.className.includes("bg-primary"));
  console.log("hover HOLE_D row -> dimension highlighted:", dimHot);
  await shot("03-hover-row-hole");

  // ---- edit the length on screen
  const s0 = await status(plate.id);
  await clickAt("[data-dim=L]");
  const input = await page.waitForSelector("[data-dim-edit=L] input", { visible: true });
  await input.type("150");
  await shot("04-edit-length");
  const tEdit = Date.now();
  await page.keyboard.press("Enter");
  const s1 = await waitBuildChange(plate.id, s0.build_id);
  await page.waitForFunction(() => [...document.querySelectorAll("[data-dim=L]")].some(e => e.textContent === "150"), { timeout: 60000 });
  console.log("edit L 120 -> 150: rebuilt", s1.fingerprint.bbox, "ok", s1.ok, "label updated after", (Date.now() - tEdit) / 1000, "s");
  await sleep(1500);
  console.log("labels", (await dimTexts()).join(", "));
  await shot("05-length-150");

  // ---- undo
  await page.mouse.move(800, 500);
  const tUndo = Date.now();
  await page.keyboard.down("Control"); await page.keyboard.press("z"); await page.keyboard.up("Control");
  const s2 = await waitBuildChange(plate.id, s1.build_id);
  await page.waitForFunction(() => [...document.querySelectorAll("[data-dim=L]")].some(e => e.textContent === "120"), { timeout: 60000 });
  console.log("undo: bbox", s2.fingerprint.bbox, "label back after", (Date.now() - tUndo) / 1000, "s");
  await sleep(1200);
  await shot("06-undo");

  // ---- invalid value: limits enforced in the input
  await clickAt("[data-dim=T]");
  const inT = await page.waitForSelector("[data-dim-edit=T] input", { visible: true });
  await inT.type("99"); await page.keyboard.press("Enter"); await sleep(300);
  const err = await page.$eval("[data-dim-edit=T]", e => e.textContent);
  console.log("T = 99:", err);
  await shot("07-limit");
  await page.keyboard.press("Escape"); await sleep(300);

  // ---- views
  await page.keyboard.down("Control"); await page.keyboard.press("3"); await page.keyboard.up("Control"); await sleep(1200);
  await shot("08-plate-top-view");
  await page.keyboard.down("Control"); await page.keyboard.press("2"); await page.keyboard.up("Control"); await sleep(1200);
  await shot("09-plate-front-view");

  // ---- flange: count, diameters, PCD
  await open(flange.id);
  const tf = await waitDims(4); await sleep(1000);
  console.log("flange dims after", tf, "s:", (await dimTexts()).join(", "), JSON.stringify((await api("GET", `/api/projects/${flange.id}/dims`)).body.timings));
  await shot("10-flange");
  const sf = await status(flange.id);
  await clickAt("[data-dim=N_BOLTS]");
  const inN = await page.waitForSelector("[data-dim-edit=N_BOLTS] input", { visible: true });
  await inN.type("8"); await page.keyboard.press("Enter");
  await waitBuildChange(flange.id, sf.build_id);
  await page.waitForFunction(() => [...document.querySelectorAll("[data-dim=N_BOLTS]")].some(e => e.textContent === "8×"), { timeout: 90000 });
  await sleep(1500);
  console.log("flange 8 holes:", (await dimTexts()).join(", "), JSON.stringify((await api("GET", `/api/projects/${flange.id}/dims`)).body.timings));
  await shot("11-flange-8-holes");

  // ---- shaft
  await open(shaft.id);
  const ts = await waitDims(4); await sleep(1000);
  console.log("shaft dims after", ts, "s:", (await dimTexts()).join(", "));
  await shot("12-shaft");

  // ---- toolbox component
  const tb = (await api("POST", "/api/projects", { name: "Toolbox dowel" })).body.id;
  const ins = await api("POST", `/api/projects/${tb}/toolbox`, { code: "standoff", params: {} });
  console.log("toolbox insert", ins.status);
  await open(tb);
  const tt = await waitDims(2); await sleep(1000);
  console.log("toolbox dims after", tt, "s:", (await dimTexts()).join(", "));
  await shot("13-toolbox-standoff");

  // ---- toggle off with the toolbar button
  await clickAt("[data-dims-toggle]"); await sleep(500);
  console.log("after toggle off:", (await dimTexts()).length, "labels");
} catch (e) {
  console.error("FAILED", e);
  await shot("99-failure");
  t.problems.push(String(e));
}
await t.finish();
