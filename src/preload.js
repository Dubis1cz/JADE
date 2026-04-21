const { contextBridge, ipcRenderer, webFrame } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  minimize:        () => ipcRenderer.send('window-minimize'),
  maximize:        () => ipcRenderer.send('window-maximize'),
  close:           () => ipcRenderer.send('window-close'),
  hide:            () => ipcRenderer.send('window-hide'),
  getDisplays:     () => ipcRenderer.invoke('get-displays'),
  moveToDisplay:   (id) => ipcRenderer.send('window-move-to-display', id),
  getWinPosition:  () => ipcRenderer.invoke('get-win-position'),
  setWinPosition:  (x, y) => ipcRenderer.send('window-set-position', { x, y }),
  getVersion:      () => ipcRenderer.invoke('get-version'),
  checkUpdate:     () => ipcRenderer.send('check-update'),
  setAutoStart:    (enable) => ipcRenderer.send('set-autostart', enable),
  getAutoStart:    () => ipcRenderer.invoke('get-autostart'),
  getHotkey:       () => ipcRenderer.invoke('get-hotkey'),
  setHotkey:       (keys) => ipcRenderer.invoke('set-hotkey', keys),
  setZoom:         (factor) => webFrame.setZoomFactor(factor),
  getZoom:         () => webFrame.getZoomFactor(),
});
