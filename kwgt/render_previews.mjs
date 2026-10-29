// Render previews/*.svg (written by build.py) into JPG thumbnails and a
// gallery image, then re-run build.py so the thumbnails land in the .kwgt.
//
//   node kwgt/render_previews.mjs
//
// Optional: PREVIEW_FONTS=<dir> containing kr.css (Noto Sans KR @font-face)
// and MaterialIcons.ttf, for faithful Korean text and icon glyphs.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
// require() so a globally installed playwright resolves too (NODE_PATH).
const { chromium } = createRequire(import.meta.url)("playwright");
const previews = path.join(here, "previews");
const fonts = process.env.PREVIEW_FONTS;

// Inlined as data: URLs, since setContent() pages cannot load file:// fonts.
function inlineCss(file) {
  return fs.readFileSync(file, "utf8").replace(/url\(([^)]+)\)/g, (_, u) =>
    `url(data:font/woff2;base64,${fs
      .readFileSync(path.join(path.dirname(file), u))
      .toString("base64")})`);
}
const fontCss = fonts
  ? `<style>${inlineCss(path.join(fonts, "kr.css"))}
     @font-face{font-family:"Material Icons";src:url(data:font/ttf;base64,${fs
       .readFileSync(path.join(fonts, "MaterialIcons.ttf"))
       .toString("base64")});}</style>`
  : "";

// A dark, colorful wallpaper so the translucent glass reads like it would
// on a home screen.
const wallpaper = `background:
  radial-gradient(60% 80% at 15% 20%, #3a2a7a 0%, transparent 60%),
  radial-gradient(50% 70% at 85% 30%, #0f5d6e 0%, transparent 60%),
  radial-gradient(70% 60% at 50% 100%, #7a2a4a 0%, transparent 65%),
  #08080c;`;

function page(svgs, gap = 0) {
  return `<!doctype html><html><head><meta charset="utf-8">${fontCss}
  <style>
    body{margin:0;${wallpaper}font-family:"Noto Sans KR",Roboto,sans-serif}
    .mi{font-family:"Material Icons"}
    .wrap{display:flex;flex-wrap:wrap;gap:${gap}px;padding:${gap}px;
      align-items:flex-start;width:max-content;max-width:${gap ? 1600 : 99999}px}
    figure{margin:0;color:#ccc;font-size:18px}
    figcaption{padding:4px 14px}
  </style></head><body><div class="wrap">${svgs}</div></body></html>`;
}

const files = fs.readdirSync(previews).filter((f) => f.endsWith(".svg")).sort();
const browser = await chromium.launch();
const ctx = await browser.newContext({ deviceScaleFactor: 1 });
const p = await ctx.newPage();
const all = [];
for (const f of files) {
  const svg = fs.readFileSync(path.join(previews, f), "utf8");
  all.push(`<figure>${svg}<figcaption>${f.replace(".svg", "")}</figcaption></figure>`);
  await p.setContent(page(svg), { waitUntil: "networkidle" });
  await p.evaluate(() => document.fonts.ready);
  const el = await p.$("svg");
  await el.screenshot({
    path: path.join(previews, f.replace(".svg", ".jpg")),
    type: "jpeg",
    quality: 88,
  });
}
await p.setViewportSize({ width: 1600, height: 1000 });
await p.setContent(page(all.join(""), 24), { waitUntil: "networkidle" });
await p.evaluate(() => document.fonts.ready);
await (await p.$(".wrap")).screenshot({
  path: path.join(previews, "gallery.png"),
});
await browser.close();
execFileSync("python3", [path.join(here, "build.py")], { stdio: "inherit" });
