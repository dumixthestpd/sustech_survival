# electron/ — Desktop wrapper for sustech_survival

Friendly launcher that bundles the existing `sustech_survival.webui` Flask app
inside a native Electron window, so non-technical users can:

- launch the toolkit **without touching a terminal or running pip install**
- save their CAS SID/password to the **OS keychain** (macOS Keychain,
  Windows DPAPI, Linux libsecret) — never plaintext to disk
- pick a UI skin (default / default_zh)
- get **auto-updates** for the Electron shell itself, via GitHub Releases
  (`dumixthestpd/sustech_survival`)
- upgrade the embedded Python module from the in-app panel
  (`pip install --upgrade sustech_survival[webui]`)

The webui module is **not replaced**. Electron is purely a friendlier shell.

## Layout

```
electron/
├── package.json          # electron + electron-builder + electron-updater
├── main.js               # BrowserWindow + spawn Flask + IPC handlers
├── preload.js            # context-isolated bridge (sandboxed renderer)
├── renderer/             # minimal settings UI (vault, skin, updates)
│   ├── index.html
│   ├── app.css
│   ├── app.js
│   └── icon.png          # torch-only logo (favicon + header brand mark)
├── build/                # icon assets for electron-builder (generated)
│   ├── icon.png          # 512×512 torch PNG (rasterized from logo.svg)
│   ├── icon-1024.png     # 1024×1024 torch PNG
│   └── icon.ico          # multi-size Windows ICO (16…256)
├── icon-gen.js           # renders resources/logo.svg → build/*.png via Electron
├── python/               # bundled portable Python (NOT checked in — see below)
│   └── win32-x64/        # python-build-standalone, sustech_survival[webui] preinstalled
└── README.md             # this file
```

## Local dev

```bash
cd electron
npm install                    # ~250MB (electron + electron-builder)
npm start                      # self-healing: reuses a Python that has the module, else auto-creates electron/.venv
```

`main.js` dev mode resolves Python in this order: `$SUSTECH_PYTHON` env var →
`D:\dumix\Applications\conda\envs\ai-sustech-dev\python.exe` → `python` on PATH,
using the first one that already has `sustech_survival`. If **none** do, it
creates an isolated venv at `electron/.venv` and pip-installs the repo
(editable) into it — **no conda/system env is ever modified**. First run
needs network (~1 min); afterwards it is instant. On this project's dev
machine the conda env already has the editable install, so `npm start` uses
it directly.

## Icons (torch-only logo everywhere)

The window/taskbar icon, the NSIS installer icon, and the renderer favicon all
use the **torch-only mark** (`src/sustech_survival/resources/logo.svg`). To
regenerate the PNG/ICO after the SVG changes:

```bash
npx electron icon-gen.js ../src/sustech_survival/resources/logo.svg build/icon.png build/icon-1024.png
python -c "from PIL import Image; im=Image.open('build/icon.png').convert('RGBA'); \
[im.resize((s,s), Image.LANCZOS).save(f'build/icon-{s}.png') for s in (256,)]; \
im.save('build/icon.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
```

## Bundling portable Python (python-build-standalone)

The `python/` directory is **not checked in**. To populate it for Windows x64:

```bash
mkdir -p python/win32-x64
curl -L https://github.com/astral-sh/python-build-standalone/releases/download/<TAG>/cpython-3.10.x+x86_64-pc-windows-msvc-install_only.tar.gz \
  | tar -xz -C python/win32-x64 --strip-components=1   # flatten the inner python/ dir
python/win32-x64/python.exe -m pip install "..[webui]"
```

For other platforms use the matching asset name (`aarch64-apple-darwin`,
`x86_64-unknown-linux-gnu`, …) with the same layout under
`python/<platform>-<arch>/`; `main.js` resolves the bundle from
`resources/python/<platform>-<arch>/`.

## Building the Windows installer

```bash
npm run build:win             # -> ../dist/electron/sustech_survival-*-setup.exe
```

The NSIS installer is **per-user, no admin needed**, lets you pick the install
directory, and creates Start Menu + desktop shortcuts. The bundled Python ships
inside the app (`resources/python/win32-x64/`), so the installed app runs fully
offline — no pip, no terminal, no Python on the user's machine.

macOS / Linux follow the same pattern (`npm run build:mac` / `build:linux`).
All installers are **unsigned** until a signing certificate is configured.

## Auto-update

When packaged with a public release tag on GitHub, `electron-updater`
checks `dumixthestpd/sustech_survival/releases` on launch. Downloaded
updates install on next quit.

For local builds, auto-update is disabled (`isDev` check in `main.js`).

## Security model

- `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`.
- Renderer only sees `window.sustech.*` — narrow IPC surface.
- Credentials go through `safeStorage.encryptString()` → OS keychain.
- External links delegate to the user's default browser via
  `shell.openExternal`.
- CSP: `default-src 'self'`.

## What's NOT in this build

- **No code signing.** Sign with Apple Developer ID / Microsoft Authenticode
  before public release.
- **No GitHub Actions workflow.** Local builds only; CI/release automation
  is a separate task.