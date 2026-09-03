# Electron — how to boot / install

Two very different paths. Read the one that matches you.

---

## A. DEVELOPER — booting the Electron app from source

You are on the dev machine (this one). The Electron shell is a wrapper: it
spawns a Python process running the webui (`python -m sustech_survival.webui
serve`) and opens a native window pointed at it.

### One-time setup

`npm start` is now **self-healing**: if no Python on the machine has
`sustech_survival`, the app creates an **isolated venv** at
`electron/.venv` and pip-installs the repo (editable) into it — your conda /
system envs are **never touched**. You only need Node:

```powershell
cd D:\dumix\.openclaw\workspace\sustech_code\sustech_survival\electron
npm install        # ~250 MB (electron + electron-builder)
npm start          # first run: creates .venv + installs [webui] (needs network, ~1 min)
```

Optional (faster first run / live code edits without the venv round-trip):
install the module into the dev env yourself, as before:

```powershell
conda activate ai-sustech-dev
pip install -e "D:\dumix\.openclaw\workspace\sustech_code\sustech_survival[webui]"
```

### Boot

```powershell
cd D:\dumix\.openclaw\workspace\sustech_code\sustech_survival\electron
npm start
```

`main.js` (dev mode) picks Python in this order:
1. `$SUSTECH_PYTHON` env var if set
2. `D:\dumix\Applications\conda\envs\ai-sustech-dev\python.exe`
3. `%USERPROFILE%\Applications\conda\envs\ai-sustech-dev\python.exe`
4. plain `python` on PATH

…and uses the **first one that already has `sustech_survival`**; if none do,
it boots from the auto-created `electron/.venv` (see above). The window opens
with the webui on a random free port (printed as
`[webui] up on http://127.0.0.1:<port>/` in the terminal).

### Verify the webui directly (no Electron)

```powershell
conda activate ai-sustech-dev
python -m sustech_survival.webui serve --port 21345 --host 127.0.0.1
# open http://127.0.0.1:21345/ in a browser
```

### Rebuilding the installer after code changes

```powershell
cd D:\dumix\.openclaw\workspace\sustech_code\sustech_survival\electron

# 1. Refresh the bundled Python's copy of the module (it's a REAL install,
#    not editable — must be re-copied after every backend change)
python\win32-x64\python.exe -m pip install --force-reinstall --no-deps ".."

# 2. Build
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npm run build:win
# -> ..\dist\electron\sustech_survival-2026.8.25-electron.1-setup.exe
```

---

## B. END USER — installing from nothing

The whole point of the installer: the user needs **zero** Python, **zero**
Node, **zero** terminal. Just the one .exe.

### Steps

1. **Get the installer** — `sustech_survival-2026.8.25-electron.1-setup.exe`
   (~115 MB). Copy it to the target machine (USB / download / whatever).

2. **Double-click it.** A normal Windows installer wizard appears
   (per-user — no admin password, no UAC). Pick install directory if you
   want, or just click through. Desktop + Start Menu shortcuts are created.

3. **Launch** via the desktop shortcut / Start Menu → "sustech_survival".

4. **First run** — a settings window opens ("Credentials" panel):
   - enter SID + password, click **Save** → stored in the Windows
     credential vault (DPAPI), never plaintext on disk
   - pick a skin (default en / default_zh) if desired
   - that's it — the main webui window opens next.

5. **Use it** — course selection, transit map, etc., all inside the window.

### What the installed app contains (no network needed at runtime)

- the Electron shell (`sustech_survival.exe`)
- a **bundled portable Python 3.10.21** at
  `resources\python\win32-x64\python.exe` — with `sustech_survival[webui]`
  already pip-installed inside it
- the torch-only logo as window/installer icon

So it runs fully offline. The only thing requiring the network is the app's
actual data — TIS/BB/etc. (and it needs to be reachable from the user's
location, e.g. campus or VPN).

### Troubleshooting (shouldn't happen, but)

- **"Bundled Python missing"** dialog → the install is broken; reinstall.
- **"could not start"** dialog → the webui failed to boot; the dialog shows
  the reason. Report it.
- **401 from TIS** → session expired; the app now auto-refreshes it. If it
  recurs, re-enter credentials in the settings window.

### Upgrading later

- The shell can self-update from GitHub Releases (`dumixthestpd/sustech_survival`)
  once a signed public release exists (auto-update is disabled for local
  builds — `isDev`/no release).
- The in-app "Upgrade Python module" button runs
  `pip install --upgrade sustech_survival[webui]` against the bundled Python.
- Simplest for the user: install the new `.exe` over the old one.
