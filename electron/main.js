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

function pythonBinary() {
  if (isDev) {
    // Dev mode: use system Python on PATH so `sustech_survival` resolves
    // via the editable install (pip install -e .).
    return process.platform === 'win32' ? 'python.exe' : 'python3';
  }
  const exe = process.platform === 'win32' ? 'python.exe' : 'bin/python3';
  return path.join(RESOURCES, 'python', exe);
}

// -- Spawn the webui as a child process -----------------------------------

let webuiProc = null;
let webuiPort = null;
let mainWindow = null;

async function startWebui() {
  webuiPort = await findFreePort();
  const py = pythonBinary();

  if (!isDev && !fs.existsSync(py)) {
    dialog.showErrorBox(
      'Bundled Python missing',
      `Could not find portable Python at ${py}.\n` +
      'Reinstall sustech_survival or report an issue.'
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
  await startWebui();

  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: 'sustech_survival',
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
  const py = pythonBinary();
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