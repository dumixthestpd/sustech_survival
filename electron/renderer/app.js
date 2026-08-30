// app.js — minimal settings UI for the Electron shell.
//
// NOTE: The Flask webui itself is the primary surface — this panel is just
// for credential vault + skin picker + update control. The real login flow
// happens inside the BrowserWindow pointing at the bundled webui.

'use strict';

const statusEl = document.getElementById('status');
const sidEl = document.getElementById('sid');
const pwEl = document.getElementById('password');
const skinEl = document.getElementById('skin');
const updateStatusEl = document.getElementById('update-status');

document.getElementById('save').addEventListener('click', async () => {
  await window.sustech.vault.set(sidEl.value.trim(), pwEl.value);
  statusEl.textContent = 'credentials saved to OS keychain';
});

document.getElementById('load').addEventListener('click', async () => {
  const { sid, password } = await window.sustech.vault.get();
  sidEl.value = sid || '';
  pwEl.value = password || '';
  statusEl.textContent = sid ? 'loaded from keychain' : 'nothing saved yet';
});

document.getElementById('clear').addEventListener('click', async () => {
  await window.sustech.vault.clear();
  sidEl.value = '';
  pwEl.value = '';
  statusEl.textContent = 'cleared';
});

skinEl.addEventListener('change', async () => {
  await window.sustech.settings.set('active_skin', skinEl.value);
  statusEl.textContent = `skin set to ${skinEl.value}`;
});

(async () => {
  const saved = await window.sustech.settings.get('active_skin');
  if (saved) skinEl.value = saved;
})();

document.getElementById('check-update').addEventListener('click', async () => {
  updateStatusEl.textContent = 'checking…';
  const r = await window.sustech.updater.check();
  updateStatusEl.textContent = r.ok ? `latest: v${r.version}` : `error: ${r.error}`;
});

document.getElementById('upgrade-python').addEventListener('click', async () => {
  updateStatusEl.textContent = 'upgrading python module…';
  const r = await window.sustech.python.upgrade();
  updateStatusEl.textContent = r.code === 0 ? 'python module upgraded' : `pip exit ${r.code}`;
});

document.getElementById('open-logs').addEventListener('click', () => {
  window.sustech.app.openLogs();
});

window.sustech.updater.onAvailable((info) => {
  updateStatusEl.textContent = `update v${info.version} downloading…`;
});

window.sustech.updater.onDownloaded((info) => {
  updateStatusEl.textContent = `v${info.version} ready — restart to install`;
});

setTimeout(() => { statusEl.textContent = 'ready'; }, 1500);