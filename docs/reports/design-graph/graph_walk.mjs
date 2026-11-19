// Design graph in the Office plan review (FW_DESIGN_GRAPH=1, intent replies replayed from the live runs).
import { start } from "./lib.mjs";

const { page, api, shot, sleep, finish, clickText } = await start();
const cases = [
  ["Keyed gear", "Build a Spur Gear mounted on stepped Shaft and locked with a key"],
  ["Gear Reducer", "Build a Single stage 3:1 reducer with Spur Gears"],
];
for (const [name, brief] of cases) {
  const r = await api("POST", "/api/office/programs", { name, brief, planner: "archie", deliverables: false });
  if (r.status !== 200) throw new Error(`create ${r.status} ${JSON.stringify(r.body)}`);
  const pid = r.body.id;
  let v = r.body;
  for (let i = 0; i < 60 && v.status !== "plan_review"; i++) { await sleep(500); v = (await api("GET", `/api/office/programs/${pid}`)).body; }
  console.log(name, v.status, "questions", JSON.stringify(v.plan?.graph?.questions?.map(q => q.id)), "check", JSON.stringify(v.plan?.graph?.check));
  await page.goto(`${process.env.FW_URL}/app/office/programs/${pid}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("[data-design-graph]", { timeout: 30000 });
  await sleep(800);
  const slug = name.toLowerCase().replace(/\s+/g, "-");
  await shot(`${slug}-plan-review`);
  const card = await page.$("[data-design-graph]");
  await card.screenshot({ path: `${process.env.OUT}/${slug}-graph-card.png` });
  if (await page.$("[data-graph-questions]")) {
    const q = await page.$("[data-graph-questions]");
    await q.screenshot({ path: `${process.env.OUT}/${slug}-questions.png` });
    await clickText("Carbon steel (C45)");
    await clickText("Apply my answers");
    for (let i = 0; i < 40; i++) { await sleep(300); if (!(await page.$("[data-graph-questions]"))) break; }
    await sleep(800);
    await shot(`${slug}-answered`);
    v = (await api("GET", `/api/office/programs/${pid}`)).body;
    console.log(name, "after answer: questions", JSON.stringify(v.plan.graph.questions), "materials",
      JSON.stringify(v.plan.graph.view.components.filter(c => c.kind === "Spur gear").map(c => c.name)));
  }
}
await finish();
