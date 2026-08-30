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
│   └── app.js
└── README.md             # this file
```

## Local dev

```bash
cd electron
npm install                    # ~250MB (electron + electron-builder)
npm start                      # uses system Python (needs editable install)
```

The dev mode assumes you've already run `pip install -e .` in the repo root
so `sustech_survival.webui` resolves.

## Building installers

```bash
npm run build:mac              # -> ../dist/electron/sustech_survival-*.dmg
npm run build:win              # -> ../dist/electron/sustech_survival-*.exe
npm run build:linux            # -> ../dist/electron/sustech_survival-*.AppImage
```

These produce **unsigned** installers for local testing. For public release,
code signing + a signing certificate are required (out of scope for now).

## Bundling portable Python (python-build-standalone)

The `python/` directory is **not checked in**. To populate it:

```bash
# macOS arm64
mkdir -p python/darwin-arm64
curl -L https://github.com/astral-sh/python-build-standalone/releases/download/20240809/cpython-3.12.5+20240809-aarch64-apple-darwin-install_only.tar.gz \
  | tar -xz -C python/darwin-arm64 --strip-components=1

# Linux x64 / arm64 — same pattern with the matching asset name.
# Windows x64 — download the .zip, extract to python/win32-x64/python.exe.
```

Then install the package into the bundled Python:

```bash
./python/darwin-arm64/bin/python3 -m pip install sustech_survival[webui]
```

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
- **No portable Python yet.** The directory is referenced but not populated.
  Add it before packaging a release.
- **No GitHub Actions workflow.** Local builds only; CI/release automation
  is a separate task.