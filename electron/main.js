// main.js — Electron main process for sustech_survival
//
// Responsibilities:
//   1. Spawn a bundled portable Python (python-build-standalone) running
//      `python -m sustech_survival.webui serve --port <free>`.
//   2. Open a BrowserWindow pointed at http://127.0.0.1:<port>/.
//   3. Expose IPC handlers via preload.js for:
//        - safeStorage credential vault (OS keychain/DPAPI/libsecret)
//        - settings persistence (electron-store)
//        - auto-update check (electron-updater, GitHub Releases)
//        - in-app Python module upgrade (`pip install --upgrade`)
//   4. Shut the Python child down cleanly on quit.
//
// This wrapper does NOT replace the webui module — Flask + Jinja skins
// remain the source of truth. Electron is purely a friendlier launcher
// for non-technical users who don't want a terminal.

'use strict';

const { app, BrowserWindow, ipcMain, safeStorage, dialog, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { autoUpdater } = require('electron-updater');

const isDev = !app.isPackaged;
const RESOURCES = isDev ? path.join(__dirname) : process.resourcesPath;

// -- Find a free port for the bundled Flask webui -------------------------

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

// -- Locate the bundled Python interpreter --------------------------------

function bundledPythonDir() {
  // Bundled portable Python (python-build-standalone) lives under
  // resources/python/<platform>-<arch>/ — e.g. python/win32-x64/python.exe.
  return path.join(RESOURCES, 'python', `${process.platform}-${process.arch}`);
}

// -- Locate the Python interpreter -----------------------------------------
//
// Packaged: the bundled portable Python (python-build-standalone) under
// resources/python/<platform>-<arch>/ — always used, env-independent.
//
// Dev: we need SOME Python with `sustech_survival` importable. Resolution:
//   1. $SUSTECH_PYTHON override, then this project's conda env
//      (ai-sustech-dev), then plain Python on PATH — the first candidate
//      that ALREADY has the module wins (fast path; nothing is installed
//      into any env).
//   2. If none of them has it, the app creates an ISOLATED venv at
//      electron/.venv and pip-installs the repo (editable) into it — the
//      user's conda/system envs are NEVER touched. First run needs network
//      and takes about a minute; afterwards it is instant.

function bundledPythonDir() {
  // Bundled portable Python (python-build-standalone) lives under
  // resources/python/<platform>-<arch>/ — e.g. python/win32-x64/python.exe.
  return path.join(RESOURCES, 'python', `${process.platform}-${process.arch}`);
}

const DEV_VENV_DIR = path.join(__dirname, '.venv');

function venvPythonPath() {
  return process.platform === 'win32'
    ? path.join(DEV_VENV_DIR, 'Scripts', 'python.exe')
    : path.join(DEV_VENV_DIR, 'bin', 'python');
}

function basePythonBinary() {
  // Dev candidates, in order. Only existence is checked here; module
  // presence is probed by ensureDevPython().
  const envCandidates = [
    process.env.SUSTECH_PYTHON,                       // explicit override
    'D:\\dumix\\Applications\\conda\\envs\\ai-sustech-dev\\python.exe',
    path.join(process.env.USERPROFILE || '', 'Applications', 'conda',
              'envs', 'ai-sustech-dev', 'python.exe'),
  ].filter(Boolean);
  for (const c of envCandidates) {
    if (fs.existsSync(c)) return c;
  }
  return process.platform === 'win32' ? 'python.exe' : 'python3';
}

function runQuiet(py, args) {
  // Resolve true when the command exits 0. Failure (missing interpreter,
  // crash, exit != 0) resolves false. Output is discarded.
  return new Promise((resolve) => {
    const proc = spawn(py, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    proc.stdout.resume();
    proc.stderr.resume();
    proc.on('error', () => resolve(false));
    proc.on('exit', (code) => resolve(code === 0));
  });
}

function runLogged(py, args, tag) {
  // Run a longer bootstrap step (venv create / pip install) with its
  // output streamed to the terminal under [tag].
  return new Promise((resolve) => {
    const proc = spawn(py, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    proc.stdout.on('data', (b) => console.log(`[${tag}]`, b.toString().trimEnd()));
    proc.stderr.on('data', (b) => console.error(`[${tag}:err]`, b.toString().trimEnd()));
    proc.on('error', (e) => {
      console.error(`[${tag}] failed to launch:`, e);
      resolve(false);
    });
    proc.on('exit', (code) => resolve(code === 0));
  });
}

async function ensureDevPython() {
  // Fast path: reuse a Python that already has the module. Nothing is
  // installed anywhere — the user's envs stay exactly as they are.
  const base = basePythonBinary();
  if (await runQuiet(base, ['-c', 'import sustech_survival'])) {
    return base;
  }

  // Isolated fallback: electron/.venv, created FROM `base` (the base
  // interpreter is only used to create the venv, never polluted).
  const venvPy = venvPythonPath();
  if (fs.existsSync(venvPy)) {
    if (await runQuiet(venvPy, ['-c', 'import sustech_survival'])) {
      console.log(`[venv] using existing ${venvPy}`);
      return venvPy;
    }
    console.log('[venv] existing .venv is stale — re-creating');
    fs.rmSync(DEV_VENV_DIR, { recursive: true, force: true });
  }

  console.log(`[venv] creating isolated venv at ${DEV_VENV_DIR} …`);
  if (!await runLogged(base, ['-m', 'venv', DEV_VENV_DIR], 'venv')) {
    throw new Error(`failed to create venv with ${base} (python -m venv)`);
  }
  console.log('[venv] installing sustech_survival[webui] (editable, from the repo) …');
  const repoRoot = path.join(__dirname, '..');
  if (!await runLogged(venvPy,
                       ['-m', 'pip', 'install', '--disable-pip-version-check',
                        '-e', `${repoRoot}[webui]`], 'venv')) {
    throw new Error('failed to pip install sustech_survival[webui] into the venv');
  }
  console.log(`[venv] ready — using ${venvPy}`);
  return venvPy;
}

async function pythonBinary() {
  if (isDev) return ensureDevPython();
  const exe = process.platform === 'win32' ? 'python.exe' : 'bin/python3';
  return path.join(bundledPythonDir(), exe);
}

// -- Spawn the webui as a child process -----------------------------------

let webuiProc = null;
let webuiPort = null;
let mainWindow = null;

function windowIcon() {
  // Torch-only logo as the window/taskbar icon. Packaged: resources
  // folder; dev: electron/build/.
  const candidates = [
    path.join(RESOURCES, 'icon.png'),
    path.join(__dirname, 'build', 'icon.png'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return undefined;
}

async function startWebui() {
  webuiPort = await findFreePort();
  const py = await pythonBinary();

  if (!isDev && !fs.existsSync(py)) {
    dialog.showErrorBox(
      'Bundled Python missing',
      `Could not find portable Python at ${py}.\n` +
      'This build was not packaged with a Python runtime — ' +
      'reinstall sustech_survival from the official installer, or ' +
      'report this issue.'
    );
    app.quit();
    return;
  }

  const args = ['-m', 'sustech_survival.webui', 'serve', '--port', String(webuiPort)];
  webuiProc = spawn(py, args, {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });

  webuiProc.stdout.on('data', (b) => console.log('[webui]', b.toString().trimEnd()));
  webuiProc.stderr.on('data', (b) => console.error('[webui:err]', b.toString().trimEnd()));
  webuiProc.on('exit', (code) => {
    console.log(`[webui] exited with code ${code}`);
    webuiProc = null;
  });

  // Wait up to 10s for the webui to start serving.
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      await new Promise((resolve, reject) => {
        const sock = net.connect(webuiPort, '127.0.0.1');
        sock.once('connect', () => { sock.end(); resolve(); });
        sock.once('error', reject);
        setTimeout(() => { sock.destroy(); reject(new Error('timeout')); }, 500);
      });
      console.log(`[webui] up on http://127.0.0.1:${webuiPort}/`);
      return;
    } catch { /* not ready yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`webui did not start within 10s`);
}

function stopWebui() {
  if (!webuiProc) return;
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(webuiProc.pid), '/t', '/f']);
    } else {
      webuiProc.kill('SIGTERM');
    }
  } catch (e) {
    console.error('[webui] kill failed:', e);
  }
}

// -- BrowserWindow --------------------------------------------------------

async function createWindow() {
  try {
    await startWebui();
  } catch (e) {
    console.error('[webui] failed to start:', e);
    dialog.showErrorBox(
      'sustech_survival could not start',
      'The built-in web service failed to start.\n\n' +
      String(e && e.message ? e.message : e) + '\n\n' +
      'If this is a development build: the app auto-installs the module ' +
      'into electron/.venv when no Python has it (first run needs network; ' +
      'see the terminal log). Otherwise install it into the Python being ' +
      'used (pip install -e ".[webui]").'
    );
    app.quit();
    return;
  }

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'sustech_survival',
    icon: windowIcon(),
    backgroundColor: '#0f1115',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  await mainWindow.loadURL(`http://127.0.0.1:${webuiPort}/`);

  // External links open in the user's browser, not inside Electron.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// -- IPC: secure credential vault (OS keychain via safeStorage) ----------

const STORE_KEY_SID = 'credentials.sid';
const STORE_KEY_PW = 'credentials.password';

ipcMain.handle('vault:set', (_e, { sid, password }) => {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('OS credential vault unavailable on this system');
  }
  const Store = require('electron-store');
  const store = new Store({ name: 'sustech_survival' });
  if (sid != null) {
    if (sid === '') store.delete(STORE_KEY_SID);
    else store.set(STORE_KEY_SID, safeStorage.encryptString(sid));
  }
  if (password != null) {
    if (password === '') store.delete(STORE_KEY_PW);
    else store.set(STORE_KEY_PW, safeStorage.encryptString(password));
  }
  return { ok: true };
});

ipcMain.handle('vault:get', () => {
  const Store = require('electron-store');
  const store = new Store({ name: 'sustech_survival' });
  const out = { sid: '', password: '' };
  const encSid = store.get(STORE_KEY_SID);
  const encPw = store.get(STORE_KEY_PW);
  if (encSid && safeStorage.isEncryptionAvailable()) out.sid = safeStorage.decryptString(Buffer.from(encSid));
  if (encPw && safeStorage.isEncryptionAvailable()) out.password = safeStorage.decryptString(Buffer.from(encPw));
  return out;
});

ipcMain.handle('vault:clear', () => {
  const Store = require('electron-store');
  const store = new Store({ name: 'sustech_survival' });
  store.delete(STORE_KEY_SID);
  store.delete(STORE_KEY_PW);
  return { ok: true };
});

// -- IPC: settings (active skin, window geometry, etc.) -------------------

ipcMain.handle('settings:get', (_e, key) => {
  const Store = require('electron-store');
  const store = new Store({ name: 'sustech_survival' });
  return store.get(key);
});

ipcMain.handle('settings:set', (_e, { key, value }) => {
  const Store = require('electron-store');
  const store = new Store({ name: 'sustech_survival' });
  store.set(key, value);
  return { ok: true };
});

// -- IPC: Python module upgrade (`pip install --upgrade`) -----------------

ipcMain.handle('python:upgrade', async () => {
  const py = await pythonBinary();
  return new Promise((resolve) => {
    const proc = spawn(py, ['-m', 'pip', 'install', '--upgrade', 'sustech_survival[webui]'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '', err = '';
    proc.stdout.on('data', (b) => { out += b.toString(); });
    proc.stderr.on('data', (b) => { err += b.toString(); });
    proc.on('close', (code) => resolve({ code, stdout: out, stderr: err }));
  });
});

// -- IPC: open log directory ----------------------------------------------

ipcMain.handle('app:openLogs', () => {
  const logDir = isDev
    ? path.join(__dirname, '..', 'logs')
    : path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(logDir, { recursive: true });
  shell.openPath(logDir);
  return { logDir };
});

// -- Auto-update (electron-updater, GitHub Releases) ----------------------

function setupAutoUpdater() {
  if (isDev) return; // never auto-update during local dev
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    if (mainWindow) mainWindow.webContents.send('update:available', info);
  });
  autoUpdater.on('update-downloaded', (info) => {
    if (mainWindow) mainWindow.webContents.send('update:downloaded', info);
  });
  autoUpdater.on('error', (err) => {
    console.error('[updater] error:', err);
  });
}

ipcMain.handle('updater:check', async () => {
  if (isDev) return { skipped: 'dev-mode' };
  try {
    const result = await autoUpdater.checkForUpdates();
    return { ok: true, version: result?.updateInfo?.version };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle('updater:install', () => {
  if (isDev) return { skipped: 'dev-mode' };
  autoUpdater.quitAndInstall();
});

// -- App lifecycle --------------------------------------------------------

app.whenReady().then(async () => {
  setupAutoUpdater();
  await createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopWebui();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => { stopWebui(); });