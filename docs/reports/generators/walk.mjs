// Generators walkthrough: the reducer program's Board, a direct-built ticket, the Assembly tab, the templates panel.
import { start } from "./lib.mjs";

const { page, api, clickAt, shot, sleep, finish } = await start();
const progs = await api("GET", "/api/office/programs");
const p = (progs.body.items || []).find(x => /reduc/i.test(x.name)) || progs.body.items[0];
console.log("program", p.id, p.name, p.status);
const view = await api("GET", `/api/office/programs/${p.id}`);
const parts = view.body.tickets.filter(t => t.kind === "part");
for (const t of parts) console.log(`  ${t.title}: ${t.direct ? t.direct.path : "-"} ${t.direct?.summary ?? (t.direct?.reasons ?? []).join("; ")} tokens=${t.tokens}`);
await page.goto(`${process.env.FW_URL}/app/office/programs/${p.id}?tab=board`, { waitUntil: "domcontentloaded" });
await sleep(4000);
await shot("01-board");
const housing = parts.find(t => /housing base/i.test(t.title)) || parts[0];
await clickAt(`::-p-text(${housing.title})`, { timeout: 30000 });
await sleep(1500);
await shot("02-drawer-housing");
await page.keyboard.press("Escape");
await page.goto(`${process.env.FW_URL}/app/office/programs/${p.id}?tab=assembly`, { waitUntil: "domcontentloaded" });
await sleep(12000);
await shot("03-assembly");
await page.goto(`${process.env.FW_URL}/app/office`, { waitUntil: "domcontentloaded" });
await sleep(3000);
await shot("04-office-home");
await finish();
