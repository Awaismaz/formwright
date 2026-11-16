// DS-024 walkthrough: revolve from the Front plane, cut from an offset Top plane, circular pattern of the cut.
import { BASE, start } from "./lib.mjs";

const t = await start();
const { page, api, clickAt, clickText, shot, sleep } = t;

/** Map sketch mm -> screen px by reading the sketcher's cursor readout at two points. */
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
const waitBuild = async () => { await page.waitForSelector("svg.touch-none", { hidden: true, timeout: 180000 }); await sleep(2500); };
const status = async pid => (await api("GET", `/api/projects/${pid}/files/status.json`)).body;

try {
  const pid = (await api("POST", "/api/projects", { name: "Bushing by hand" })).body.id;
  await page.goto(`${BASE}/app/projects/${pid}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-tour=command-manager]"); await sleep(1500);
  await clickText("Features");
  await clickText("Revolved Boss/Base");
  await sleep(300);
  await clickAt("button[data-plane=Front]"); await sleep(500);
  let px = await calibrate();
  await clickAt('button[aria-label="Centerline (construction; the revolve axis)"]');
  await page.mouse.click(...px(0, -25)); await sleep(150); await page.mouse.click(...px(0, 25)); await sleep(200);
  await clickAt('button[aria-label="Corner rectangle"]');
  await page.mouse.click(...px(10, -15)); await sleep(150); await page.mouse.click(...px(20, 15)); await sleep(300);
  await shot("20-revolve-sketch");
  await clickText("Exit sketch & create");
  await waitBuild();
  await shot("21-revolved");
  let st = await status(pid);
  console.log("revolve", JSON.stringify({ ok: st?.ok, bbox: st?.fingerprint?.bbox, volume: st?.fingerprint?.volume, expected: Math.PI * 300 * 30 }));

  // cut a hole from the Top plane offset to the top face (z = 15), through all
  await clickText("Extruded Cut"); await sleep(300);
  const off = await page.waitForSelector("input[aria-label='Plane offset']");
  await off.click({ clickCount: 3 }); await off.type("15");
  await clickAt("button[data-plane=Top]"); await sleep(600);
  px = await calibrate();
  await clickAt('button[aria-label="Circle"]');
  await page.mouse.click(...px(15, 0)); await sleep(150); await page.mouse.click(...px(17, 0)); await sleep(300);
  await page.select('select[aria-label="End condition"]', "through"); await sleep(200);
  await shot("22-cut-sketch");
  await clickText("Exit sketch & create");
  await waitBuild();
  st = await status(pid);
  console.log("cut", JSON.stringify({ ok: st?.ok, volume: st?.fingerprint?.volume }));

  await clickText("Circular Pattern"); await sleep(500);
  await shot("23-cirpattern-pm");
  await clickText("Add feature");
  await page.waitForSelector("::-p-text(Add feature)", { hidden: true, timeout: 180000 }); await sleep(2500);
  await shot("24-cirpattern");
  st = await status(pid);
  console.log("pattern", JSON.stringify({ ok: st?.ok, volume: st?.fingerprint?.volume, expected: Math.PI * 300 * 30 - 6 * Math.PI * 4 * 30,
    feats: st?.features?.map(f => f.name) }));
} catch (e) {
  t.problems.push(`script: ${e.stack ?? e}`);
  await shot("zz-failure").catch(() => {});
}
await t.finish();
