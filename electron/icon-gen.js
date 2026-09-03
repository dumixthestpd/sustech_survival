// icon-gen.js — render the torch-only logo.svg into square PNG app icons.
// Usage: npx electron icon-gen.js <svg-path> <out-png-512> <out-png-1024>
// Reads the SVG, inlines it into a centered flexbox page, and captures
// the offscreen window — no third-party rasterizer, exact same artwork
// the webui serves as its favicon.

'use strict';

const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const fs = require('node:fs');

const svgPath = process.argv[2];
const out512 = process.argv[3];
const out1024 = process.argv[4];

if (!svgPath || !out512 || !out1024) {
  console.error('usage: npx electron icon-gen.js <svg> <out512> <out1024>');
  process.exit(1);
}

const SIZE = 1024;

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: SIZE,
    height: SIZE,
    show: false,
    frame: false,
    webPreferences: { offscreen: true },
  });

  try {
    const svg = fs.readFileSync(svgPath, 'utf-8');
    // Center the SVG inside a square canvas with ~8% breathing room,
    // matching how app icons are normally composed.
    const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:transparent;}
  #wrap{width:100%;height:100%;display:flex;align-items:center;justify-content:center;}
  svg{width:84%;height:84%;}
</style></head>
<body><div id="wrap">${svg}</div></body></html>`;
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
    await new Promise((r) => setTimeout(r, 500));

    const image = await win.webContents.capturePage();
    const png = image.toPNG();
    fs.mkdirSync(path.dirname(out512), { recursive: true });
    fs.writeFileSync(out512, png);
    console.log('wrote', out512, png.length, 'bytes');
  } catch (e) {
    console.error('icon-gen failed:', e);
    process.exit(1);
  } finally {
    app.quit();
  }
});
