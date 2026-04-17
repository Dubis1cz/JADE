const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  minimize:        () => ipcRenderer.send('window-minimize'),
  maximize:        () => ipcRenderer.send('window-maximize'),
  close:           () => ipcRenderer.send('window-close'),
  hide:            () => ipcRenderer.send('window-hide'),
  getDisplays:     () => ipcRenderer.invoke('get-displays'),
  moveToDisplay:   (id) => ipcRenderer.send('window-move-to-display', id),
  getWinPosition:  () => ipcRenderer.invoke('get-win-position'),
  setWinPosition:  (x, y) => ipcRenderer.send('window-set-position', { x, y }),
});
