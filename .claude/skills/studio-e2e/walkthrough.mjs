// Formwright browser walkthrough template (puppeteer-core). Copy to a scratch dir, `npm i puppeteer-core`, run:
//   FW_URL=http://127.0.0.1:8766 FW_EMAIL=... FW_PASSWORD=... OUT=./shots node walkthrough.mjs
// Extend steps() for the feature under test. Exits non-zero on page errors, console errors or 5xx responses.
import fs from "node:fs";
import puppeteer from "puppeteer-core";

const BASE = process.env.FW_URL ?? "http://127.0.0.1:8766";
const EMAIL = process.env.FW_EMAIL ?? "e2e@formwright.test";
const PASSWORD = process.env.FW_PASSWORD ?? "";
const OUT = process.env.OUT ?? "./shots";
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
fs.mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: true, defaultViewport: { width: 1600, height: 1000 },
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
const page = await browser.newPage();
const problems = [];
page.on("pageerror", e => problems.push(`pageerror: ${e.message}`));
page.on("console", m => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
page.on("response", r => { if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.url()}`); });

/** Same-origin API call from the page (cookies + CSRF header, like web/src/lib/api.ts). */
async function api(method, path, body) {
  return page.evaluate(async (method, path, body) => {
    const headers = { "content-type": "application/json" };
    if (method !== "GET") headers["X-FW-CSRF"] = "1";
    const r = await fetch(path, { method, headers, credentials: "same-origin", body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, method, path, body ?? null);
}
/** Real pointer click at an element's centre (Radix ignores synthetic clicks). */
async function clickAt(selector) {
  const el = await page.waitForSelector(selector, { visible: true, timeout: 15000 });
  const b = await el.boundingBox();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
  await page.mouse.down(); await page.mouse.up();
}
const clickText = text => clickAt(`::-p-text(${text})`);
const shot = async name => { await page.screenshot({ path: `${OUT}/${name}.png` }); console.log(`shot ${OUT}/${name}.png`); };
const idle = () => page.waitForNetworkIdle({ idleTime: 800, timeout: 60000 }).catch(() => {});

async function setup() {
  await page.goto(BASE, { waitUntil: "networkidle0" });
  await page.evaluate(() => { localStorage.setItem("fw_tour_app", "1"); localStorage.setItem("fw_tour_studio", "1"); });
  const login = await api("POST", "/api/auth/login", { email: EMAIL, password: PASSWORD });
  if (login.status !== 200) throw new Error(`login failed: ${login.status} ${JSON.stringify(login.body)}`);
  const me = await api("GET", "/api/auth/me");
  if (!me.body?.org) {
    const ob = await api("POST", "/api/onboarding", { workspace_name: "E2E workspace", units: "mm", role: "Mechanical engineer" });
    if (ob.status !== 200) throw new Error(`onboarding failed: ${ob.status} ${JSON.stringify(ob.body)}`);
  }
  await api("POST", "/api/tour/complete");
  const seed = await api("POST", "/api/god/seed-demo");
  console.log("seed-demo", seed.status, JSON.stringify(seed.body));
}

async function steps() {
  const projects = (await api("GET", "/api/projects")).body?.items ?? [];
  const demo = projects.find(p => p.name.startsWith("Demo ·")) ?? projects[0];
  if (!demo) throw new Error("no project to open");
  await page.goto(`${BASE}/app/projects/${demo.id}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-tour=command-manager]");
  await idle();
  await shot("01-studio");
  const st = await api("GET", `/api/projects/${demo.id}/files/status.json`);
  console.log("status", st.status, JSON.stringify({ ok: st.body?.ok, fingerprint: st.body?.fingerprint }));
  // --- add the flow under test here, e.g.:
  // await clickText("Features"); await clickText("Fillet"); ... await shot("02-fillet");
}

let code = 0;
try {
  await setup();
  await steps();
} catch (e) {
  problems.push(`script: ${e.stack ?? e}`);
  await shot("zz-failure").catch(() => {});
} finally {
  await browser.close();
}
if (problems.length) { console.error("PROBLEMS:\n" + problems.join("\n")); code = 1; } else console.log("0 errors");
process.exit(code);
