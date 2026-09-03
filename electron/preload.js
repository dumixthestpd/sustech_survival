// preload.js — context-isolated bridge between renderer and main.
//
// Exposes a narrow `sustech` API to the renderer. The renderer has no
// Node access; everything goes through here.

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('sustech', {
  // Credential vault (OS keychain via safeStorage).
  vault: {
    set: (sid, password) => ipcRenderer.invoke('vault:set', { sid, password }),
    get: () => ipcRenderer.invoke('vault:get'),
    clear: () => ipcRenderer.invoke('vault:clear'),
  },

  // Settings (active skin, last-opened page, etc.).
  settings: {
    get: (key) => ipcRenderer.invoke('settings:get', key),
    set: (key, value) => ipcRenderer.invoke('settings:set', { key, value }),
  },

  // Python module operations.
  python: {
    upgrade: () => ipcRenderer.invoke('python:upgrade'),
  },

  // Auto-update.
  updater: {
    check: () => ipcRenderer.invoke('updater:check'),
    install: () => ipcRenderer.invoke('updater:install'),
    onAvailable: (cb) => ipcRenderer.on('update:available', (_e, info) => cb(info)),
    onDownloaded: (cb) => ipcRenderer.on('update:downloaded', (_e, info) => cb(info)),
  },

  // Misc.
  app: {
    openLogs: () => ipcRenderer.invoke('app:openLogs'),
  },
});