// Shared helpers for Formwright walkthroughs (derived from .claude/skills/studio-e2e/walkthrough.mjs).
import fs from "node:fs";
import puppeteer from "puppeteer-core";

export const BASE = process.env.FW_URL ?? "http://127.0.0.1:8766";
const EMAIL = process.env.FW_EMAIL ?? "e2e@formwright.test";
const PASSWORD = process.env.FW_PASSWORD ?? "E2e-walkthrough-2026";
export const OUT = process.env.OUT ?? "./shots";
const CHROME = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";

export async function start() {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: { width: 1600, height: 1000 },
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const page = await browser.newPage();
  const problems = [];
  page.on("pageerror", e => problems.push(`pageerror: ${e.message}`));
  page.on("console", m => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
  page.on("response", r => { if (r.status() >= 500) problems.push(`HTTP ${r.status()} ${r.url()}`); });
  const api = (method, path, body) => page.evaluate(async (method, path, body) => {
    const headers = { "content-type": "application/json" };
    if (method !== "GET") headers["X-FW-CSRF"] = "1";
    const r = await fetch(path, { method, headers, credentials: "same-origin", body: body ? JSON.stringify(body) : undefined });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, method, path, body ?? null);
  const clickAt = async (selector, opts = {}) => {
    const el = await page.waitForSelector(selector, { visible: true, timeout: opts.timeout ?? 15000 });
    const b = await el.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down(); await page.mouse.up();
  };
  const clickText = (text, opts) => clickAt(`::-p-text(${text})`, opts);
  const shot = async name => { await page.screenshot({ path: `${OUT}/${name}.png` }); console.log(`shot ${OUT}/${name}.png`); };
  const idle = (ms = 800) => page.waitForNetworkIdle({ idleTime: ms, timeout: 20000, concurrency: 1 }).catch(() => {});
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  await page.goto(BASE, { waitUntil: "networkidle0" });
  await page.evaluate(() => { localStorage.setItem("fw_tour_app", "1"); localStorage.setItem("fw_tour_studio", "1"); });
  const login = await api("POST", "/api/auth/login", { email: EMAIL, password: PASSWORD });
  if (login.status !== 200) throw new Error(`login failed: ${login.status} ${JSON.stringify(login.body)}`);
  const me = await api("GET", "/api/auth/me");
  if (!me.body?.org) await api("POST", "/api/onboarding", { workspace_name: "E2E workspace", units: "mm", role: "Mechanical engineer" });
  await api("POST", "/api/tour/complete");
  const finish = async () => {
    await browser.close();
    if (problems.length) { console.error("PROBLEMS:\n" + problems.join("\n")); process.exit(1); }
    console.log("0 errors"); process.exit(0);
  };
  return { browser, page, api, clickAt, clickText, shot, idle, sleep, problems, finish };
}
