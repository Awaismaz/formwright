// Viewport dimensions on a part built by the design agent (replayed turn, no model call): build from chat,
// dimensions on, change the bolt count on screen, undo.
import { BASE, start } from "./lib.mjs";

const t = await start();
const { page, api, clickAt, shot, sleep } = t;
const status = async pid => (await api("GET", `/api/projects/${pid}/files/status.json`)).body;
const dimTexts = () => page.$$eval("[data-dim]", els => els.map(e => `${e.getAttribute("data-dim")}=${e.textContent}`));
const waitBuildChange = async (pid, from, timeout = 240000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) { const s = await status(pid).catch(() => null); if (s?.build_id && s.build_id !== from) return s; await sleep(500); }
  throw new Error("no rebuild");
};
try {
  await page.evaluate(() => { localStorage.setItem("fw_view_dims", "1"); localStorage.setItem("fw_studio_chat", "1"); });
  const pid = (await api("POST", "/api/projects", { name: "Motor mount (agent)" })).body.id;
  await page.goto(`${BASE}/app/projects/${pid}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-tour=command-manager]", { timeout: 120000 }); await sleep(2000);
  const c = await api("POST", `/api/projects/${pid}/agent/chat`, { prompt: "Build a motor mount: 140 x 70 x 8 mm base, 60 mm wall, 4 bolts on a 44 mm circle, 22 mm pilot bore, two M6 slots, R5 inside fillet", skip_brief: true });
  console.log("chat", c.status);
  const s0 = await waitBuildChange(pid, undefined);
  console.log("agent build", s0.ok, s0.fingerprint?.bbox);
  const t0 = Date.now();
  await page.waitForFunction(() => document.querySelectorAll("[data-dim]").length >= 8, { timeout: 170000 });
  await sleep(1500);
  const d = (await api("GET", `/api/projects/${pid}/dims`)).body;
  console.log("dims shown", (Date.now() - t0) / 1000, "s after the build;", JSON.stringify(d.timings));
  console.log("labels", (await dimTexts()).join(", "));
  await shot("20-agent-motor-mount");
  await clickAt("[data-dim=BOLT_N]");
  const inp = await page.waitForSelector("[data-dim-edit=BOLT_N] input", { visible: true });
  await inp.type("6");
  await shot("21-agent-edit-bolts");
  await page.keyboard.press("Enter");
  const s1 = await waitBuildChange(pid, s0.build_id);
  await page.waitForFunction(() => [...document.querySelectorAll("[data-dim=BOLT_N]")].some(e => e.textContent === "6×"), { timeout: 170000 });
  await sleep(1500);
  console.log("6 bolts:", s1.ok, (await dimTexts()).join(", "), JSON.stringify((await api("GET", `/api/projects/${pid}/dims`)).body.timings));
  await shot("22-agent-six-bolts");
  await page.mouse.move(700, 600);
  await page.keyboard.down("Control"); await page.keyboard.press("z"); await page.keyboard.up("Control");
  await waitBuildChange(pid, s1.build_id);
  await page.waitForFunction(() => [...document.querySelectorAll("[data-dim=BOLT_N]")].some(e => e.textContent === "4×"), { timeout: 170000 });
  console.log("undo -> 4 bolts");
  await sleep(1000);
  await shot("23-agent-undo");
} catch (e) {
  console.error("FAILED", e); await shot("98-agent-failure"); t.problems.push(String(e));
}
await t.finish();
