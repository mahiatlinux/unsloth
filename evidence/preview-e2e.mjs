import { chromium } from "playwright";
import { stubBody } from "./stub.mjs";
import { mkdirSync } from "node:fs";

const [, , baseUrl, outDir, label] = process.argv;
mkdirSync(outDir, { recursive: true });

const FIXTURES = [
  "preview_fixture.py",
  "preview_fixture.html",
  "preview_fixture.pdf",
  "preview_fixture.docx",
  "preview_fixture.txt",
  "preview_fixture.wav",
];
const dir = new URL("./fixtures/", import.meta.url).pathname;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.addInitScript(() => {
  localStorage.setItem("unsloth_auth_token", "e2e");
  localStorage.setItem("unsloth_auth_refresh_token", "e2e");
});
await page.route(
  (u) => u.pathname.startsWith("/api/"),
  async (r) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stubBody(new URL(r.request().url()).pathname)),
    }),
);

await page.goto(`${baseUrl}/chat`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(6000);

await page.getByLabel("Tools and attachments").click();
const chooser = page.waitForEvent("filechooser");
await page.getByRole("menuitem", { name: "Add photos & files" }).click();
await (await chooser).setFiles(FIXTURES.map((f) => dir + f));
await page.waitForTimeout(3000);
await page.keyboard.press("Escape");
await page.waitForTimeout(500);
await page.screenshot({ path: `${outDir}/00-composer.png` });

const results = [];
for (const name of FIXTURES) {
  const tile = page.locator(`[aria-label*="${name}"]`).first();
  const count = await tile.count();
  if (count === 0) {
    results.push({ name, opened: false, why: "no tile" });
    continue;
  }
  await tile.click();
  await page.waitForTimeout(2500);

  const dialog = page.locator('[role=dialog]').last();
  const opened = (await dialog.count()) > 0 && (await dialog.isVisible());
  if (!opened) {
    results.push({ name, opened: false, why: "no dialog" });
    await page.keyboard.press("Escape");
    continue;
  }
  const title = await dialog.locator("h2, [data-slot=dialog-title]").first().innerText().catch(() => null);
  const description = await dialog.locator("[data-slot=dialog-description]").first().innerText().catch(() => null);
  const body = await dialog.locator("pre").first().innerText().catch(() => "");
  const html = await dialog.innerHTML();
  results.push({
    name,
    opened: true,
    title,
    description,
    chars: body.length,
    lines: body ? body.split("\n").length : 0,
    shikiLines: (html.match(/--shiki-/g) ?? []).length,
    codeBlock: html.includes("data-streamdown=\"code-block\""),
    audioPlayer: (await dialog.locator("audio").count()) > 0 || html.includes("AudioPlayer") || (await dialog.locator("[class*=audio], button[aria-label*=Play], button[aria-label*=play]").count()) > 0,
    firstLines: body.split("\n").slice(0, 3),
  });
  const slug = name.replace(/\W+/g, "_");
  await page.screenshot({ path: `${outDir}/${slug}-page.png` });
  await dialog.screenshot({ path: `${outDir}/${slug}.png` }).catch(() => undefined);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(600);
}

console.log(`=== ${label} ===`);
console.log(JSON.stringify(results, null, 1));
await browser.close();
