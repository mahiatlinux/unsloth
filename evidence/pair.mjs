import { chromium } from "playwright";
import { readFileSync, mkdirSync } from "node:fs";

const PAIRS = [
  ["preview_fixture_py", "a .py in the composer", "plain monospace", "shiki, github-light"],
  ["preview_fixture_html", "an .html page", "1 line", "20 lines"],
  ["preview_fixture_pdf", "a 1 page .pdf", "1 line", "9 lines"],
  ["preview_fixture_docx", "a .docx (control)", "9 lines", "9 lines, via the fflate repack"],
  ["preview_fixture_txt", "a .txt (control)", "4 lines", "4 lines"],
  ["00-composer", "the composer, before any click (control)", "5 tiles", "5 tiles"],
];
const dir = new URL("./", import.meta.url).pathname;
mkdirSync(`${dir}pairs`, { recursive: true });
const b64 = (p) => `data:image/png;base64,${readFileSync(p).toString("base64")}`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 400 } });

for (const [slug, caption, beforeNote, afterNote] of PAIRS) {
  const html = `<!doctype html><html><body style="margin:0;background:#f6f8fa;font:14px -apple-system,Segoe UI,sans-serif">
  <div style="padding:18px 18px 10px;font-size:15px;font-weight:600;color:#1f2328">${caption}</div>
  <div style="display:flex;gap:16px;padding:0 18px 18px;align-items:flex-start">
    <div style="flex:1;min-width:0">
      <div style="font-size:12px;font-weight:600;color:#cf222e;margin-bottom:6px">BEFORE &mdash; 6b69f41d &mdash; ${beforeNote}</div>
      <img src="${b64(`${dir}before/${slug}.png`)}" style="width:100%;border:1px solid #d0d7de;border-radius:8px;background:#fff">
    </div>
    <div style="flex:1;min-width:0">
      <div style="font-size:12px;font-weight:600;color:#1a7f37;margin-bottom:6px">AFTER &mdash; bcb79bd4 &mdash; ${afterNote}</div>
      <img src="${b64(`${dir}after/${slug}.png`)}" style="width:100%;border:1px solid #d0d7de;border-radius:8px;background:#fff">
    </div>
  </div></body></html>`;
  await page.setContent(html);
  await page.waitForTimeout(400);
  const box = await page.locator("body").boundingBox();
  await page.setViewportSize({ width: 1600, height: Math.ceil(box.height) });
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${dir}pairs/${slug}.png`, fullPage: true });
  console.log("wrote", `pairs/${slug}.png`);
}
await browser.close();
