const { app, BrowserWindow, Tray, Menu, globalShortcut, shell, nativeImage, ipcMain, screen, dialog } = require('electron');
const path   = require('path');
const http   = require('http');
const { spawn, execFile } = require('child_process');
const fs     = require('fs');

// Log to file (useful for debugging packaged app)
const logFile = path.join(require('os').tmpdir(), 'jarvis-updater.log');
function logUpdate(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  console.log('[UPDATER]', msg);
  try { fs.appendFileSync(logFile, line); } catch {}
}

// Auto-updater (pouze v produkci — při vývoji se přeskočí)
let autoUpdater = null;
if (app.isPackaged) {
  try {
    autoUpdater = require('electron-updater').autoUpdater;

    autoUpdater.autoDownload         = false;  // čekáme na souhlas uživatele
    autoUpdater.autoInstallOnAppQuit = false;
    autoUpdater.logger = { info: logUpdate, warn: logUpdate, error: logUpdate, debug: () => {} };

    autoUpdater.on('update-available', (info) => {
      logUpdate(`Update available: ${info.version}`);
      dialog.showMessageBox({
        type:      'question',
        title:     'J.A.D.E. — Update Available',
        message:   `New version ${info.version} is available.`,
        detail:    `You are running v${app.getVersion()}.\nThe update will install silently in the background.`,
        buttons:   ['Install Now', 'Later'],
        defaultId: 0,
        cancelId:  1,
        icon: path.join(__dirname, 'icon.ico'),
      }).then(({ response }) => {
        if (response === 0) {
          logUpdate('User accepted update — downloading...');
          autoUpdater.downloadUpdate();
        } else {
          logUpdate('User postponed update');
        }
      });
    });

    autoUpdater.on('download-progress', (progress) => {
      logUpdate(`Download: ${Math.round(progress.percent)}%`);
      if (mainWindow) mainWindow.setProgressBar(progress.percent / 100);
    });

    autoUpdater.on('update-downloaded', () => {
      logUpdate('Update downloaded — installing silently');
      if (mainWindow) {
        mainWindow.setProgressBar(-1);
        mainWindow.setTitle('J.A.D.E.');
      }
      // Tichá instalace bez NSIS okna — app se sama restartuje
      autoUpdater.quitAndInstall(true, true); // isSilent=true, isForceRunAfter=true
    });

    autoUpdater.on('error', (err) => {
      logUpdate(`Update error: ${err.message}`);
    });

  } catch (e) {
    console.warn('[UPDATER] electron-updater not available:', e.message);
  }
}

// Povol mikrofon a Web Speech API v Chromiu
app.commandLine.appendSwitch('enable-speech-dispatcher');
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT        = 8080;
let HOTKEY        = 'CommandOrControl+Shift+J';
const APP_NAME    = 'JADE';
const SERVER_URL  = `http://localhost:${PORT}/login.html`;

let mainWindow = null;
let tray       = null;
let pyServer   = null;
let serverReady = false;

// ── Find Python ───────────────────────────────────────────────────────────────
function findPython() {
  const { spawnSync } = require('child_process');

  // 1. Bundled portable Python (highest priority — works on any machine)
  const embeddedPython = app.isPackaged
    ? path.join(process.resourcesPath, 'python-embed', 'python.exe')
    : path.join(__dirname, '..', 'python-embed', 'python.exe');

  if (fs.existsSync(embeddedPython)) {
    console.log(`[APP] Using bundled Python: ${embeddedPython}`);
    return embeddedPython;
  }

  // 2. System Python — scan common locations
  const appData = process.env.LOCALAPPDATA || '';
  const programFiles = process.env.PROGRAMFILES || 'C:\\Program Files';
  const programFilesX86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';

  const commonPaths = [
    path.join(appData, 'Programs', 'Python', 'Python314', 'python.exe'),
    path.join(appData, 'Programs', 'Python', 'Python313', 'python.exe'),
    path.join(appData, 'Programs', 'Python', 'Python312', 'python.exe'),
    path.join(appData, 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(appData, 'Programs', 'Python', 'Python310', 'python.exe'),
    'python', 'python3', 'py',
    'C:\\Python314\\python.exe',
    'C:\\Python313\\python.exe',
    'C:\\Python312\\python.exe',
  ];

  // Scan versioned subdirs
  for (const dir of [
    path.join(appData, 'Programs', 'Python'),
    path.join(programFiles, 'Python'),
    path.join(programFilesX86, 'Python'),
  ]) {
    if (fs.existsSync(dir)) {
      try {
        fs.readdirSync(dir).sort().reverse().forEach(sub => {
          const candidate = path.join(dir, sub, 'python.exe');
          if (fs.existsSync(candidate)) commonPaths.push(candidate);
        });
      } catch {}
    }
  }

  for (const c of commonPaths) {
    try {
      const r = spawnSync(c, ['--version'], { timeout: 3000 });
      if (r.status === 0) { console.log(`[APP] Found Python: ${c}`); return c; }
    } catch {}
  }
  return null;
}

// ── Start Python server ───────────────────────────────────────────────────────
function startPythonServer() {
  return new Promise((resolve, reject) => {
    // Check if already running on port
    const net = require('net');
    const probe = net.createConnection({ port: PORT }, () => {
      probe.destroy();
      console.log('[APP] Server already running on port', PORT);
      serverReady = true;
      resolve();
    });
    probe.on('error', () => {
      // Not running — start it
      const python = findPython();
      if (!python) {
        reject(new Error('Python not found. Please install Python from python.org'));
        return;
      }

      const serverPath = app.isPackaged
        ? path.join(process.resourcesPath, 'server.py')
        : path.join(__dirname, '..', 'server.py');

      // Always use the directory where server.py lives as working dir
      const workDir = path.dirname(serverPath);

      pyServer = spawn(python, [serverPath], {
        cwd: workDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: false,
        env: { ...process.env, PYTHONPATH: '' }  // clear PYTHONPATH to avoid prefix errors
      });

      pyServer.stdout.on('data', d => {
        const msg = d.toString();
        console.log('[PY]', msg.trim());
        if (msg.includes('running') || msg.includes('8080') || msg.includes('server')) {
          serverReady = true;
          resolve();
        }
      });

      pyServer.stderr.on('data', d => {
        const msg = d.toString().trim();
        console.error('[PY ERR]', msg);
        // Some Python warnings go to stderr but server still starts fine
        if (msg.includes('running') || msg.includes('8080') || msg.includes('server')) {
          serverReady = true;
          resolve();
        }
      });
      pyServer.on('error', err => reject(err));

      // Fallback resolve after 5s
      setTimeout(() => { serverReady = true; resolve(); }, 5000);
    });
  });
}

// ── Create window ─────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1280,
    height: 780,
    minWidth: 900,
    minHeight: 600,
    frame: false,           // Frameless — JADE HUD style
    transparent: false,
    backgroundColor: '#020810',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    icon: path.join(__dirname, 'icon.ico'),
    title: 'J.A.D.E.',
    show: false,
  });

  // ── Grant microphone + media permissions ──────────────────────────────────
  mainWindow.webContents.session.setPermissionRequestHandler((wc, permission, callback) => {
    const allowed = ['media', 'microphone', 'audioCapture', 'geolocation'];
    callback(allowed.includes(permission));
  });
  mainWindow.webContents.session.setPermissionCheckHandler((wc, permission) => {
    const allowed = ['media', 'microphone', 'audioCapture'];
    return allowed.includes(permission);
  });

  // Show dark loading screen immediately (no black flash)
  mainWindow.loadFile(path.join(__dirname, 'loading.html'));

  // Wait 4s for Python to start, then clear cache + load app
  setTimeout(async () => {
    try { await mainWindow?.webContents.session.clearCache(); } catch {}
    mainWindow?.loadURL(SERVER_URL);
  }, 4000);

  // If page fails to load, keep retrying every 2s
  mainWindow.webContents.on('did-fail-load', (e, code, desc, url) => {
    if (url && url.includes('localhost')) {
      console.log('[APP] Page failed, retrying in 2s...');
      setTimeout(() => mainWindow?.loadURL(SERVER_URL), 2000);
    }
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Prevent close — hide to tray instead
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ── Tray ──────────────────────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, 'icon.ico');
  const icon = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath)
    : nativeImage.createEmpty();

  tray = new Tray(icon);
  tray.setToolTip('J.A.D.E.');

  const menu = Menu.buildFromTemplate([
    {
      label: 'Show JADE',
      click: () => toggleWindow()
    },
    { type: 'separator' },
    {
      label: `Hotkey: ${HOTKEY}`,
      enabled: false
    },
    { type: 'separator' },
    {
      label: 'Open memory folder',
      click: () => {
        const memDir = app.isPackaged
          ? path.join(process.resourcesPath, 'memories')
          : path.join(__dirname, '..', 'memories');
        shell.openPath(memDir);
      }
    },
    { type: 'separator' },
    {
      label: 'Quit JADE',
      click: () => {
        app.isQuitting = true;
        app.quit();
      }
    }
  ]);

  tray.setContextMenu(menu);
  tray.on('click', () => toggleWindow());
  tray.on('double-click', () => toggleWindow());
}

function toggleWindow() {
  if (!mainWindow) {
    createWindow();
    return;
  }
  if (mainWindow.isVisible()) {
    mainWindow.hide();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

// ── Auto-start with Windows ───────────────────────────────────────────────────
function setAutoStart(enable) {
  app.setLoginItemSettings({
    openAtLogin: enable,
    name: APP_NAME,
    args: []
  });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  // Single instance lock
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) { app.quit(); return; }

  app.on('second-instance', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });

  // IPC window controls
  ipcMain.on('window-minimize', () => mainWindow?.minimize());
  ipcMain.on('window-maximize', () => {
    if (mainWindow?.isMaximized()) mainWindow.unmaximize();
    else mainWindow?.maximize();
  });
  ipcMain.on('window-close',   () => mainWindow?.hide());
  ipcMain.on('window-hide',    () => mainWindow?.hide());

  // IPC display management
  ipcMain.handle('get-win-position', () => mainWindow ? mainWindow.getPosition() : [0, 0]);

  ipcMain.on('window-set-position', (e, { x, y }) => {
    if (!mainWindow) return;
    mainWindow.setPosition(Math.round(x), Math.round(y), false);
  });

  ipcMain.handle('get-displays', () => {
    return screen.getAllDisplays().map((d, i) => ({
      id:      d.id,
      index:   i,
      label:   `Display ${i + 1}${d.id === screen.getPrimaryDisplay().id ? ' (Primary)' : ''}`,
      width:   d.workAreaSize.width,
      height:  d.workAreaSize.height,
      x:       d.bounds.x,
      y:       d.bounds.y,
      current: mainWindow
        ? d.bounds.x <= mainWindow.getPosition()[0] &&
          mainWindow.getPosition()[0] < d.bounds.x + d.bounds.width
        : i === 0,
    }));
  });

  ipcMain.on('window-move-to-display', (e, displayId) => {
    if (!mainWindow) return;
    const displays = screen.getAllDisplays();
    const target = displays.find(d => d.id === displayId) || displays[displayId];
    if (!target) return;
    const { x, y, width, height } = target.workArea;
    // Centre window on target display
    const [winW, winH] = mainWindow.getSize();
    const nx = Math.round(x + (width  - winW) / 2);
    const ny = Math.round(y + (height - winH) / 2);
    mainWindow.setPosition(nx, ny, true);
    mainWindow.focus();
  });

  // IPC — version & updater
  ipcMain.handle('get-version',  () => app.getVersion());
  ipcMain.on('check-update', () => {
    if (autoUpdater) autoUpdater.checkForUpdates();
    else dialog.showMessageBox({ type: 'info', title: 'J.A.D.E.', message: 'Update check only works in packaged app.', buttons: ['OK'] });
  });

  // IPC — autostart
  ipcMain.on('set-autostart', (e, enable) => setAutoStart(enable));
  ipcMain.handle('get-autostart', () => app.getLoginItemSettings().openAtLogin);

  // IPC — hotkey
  ipcMain.handle('get-hotkey', () => HOTKEY);
  ipcMain.handle('set-hotkey', (e, keys) => {
    try {
      globalShortcut.unregister(HOTKEY);
      const ok = globalShortcut.register(keys, () => toggleWindow());
      if (ok) { HOTKEY = keys; return { ok: true }; }
      else { globalShortcut.register(HOTKEY, () => toggleWindow()); return { ok: false, error: 'Hotkey already in use' }; }
    } catch(err) {
      globalShortcut.register(HOTKEY, () => toggleWindow());
      return { ok: false, error: err.message };
    }
  });

  // Enable autostart
  setAutoStart(true);

  // Create tray first
  createTray();

  // Start Python server
  try {
    await startPythonServer();
    console.log('[APP] Server ready');
  } catch (err) {
    console.error('[APP] Server error:', err.message);
  }

  // Create window
  createWindow();

  // Check for updates 5s after start (only in packaged app)
  if (autoUpdater) {
    setTimeout(() => autoUpdater.checkForUpdates(), 5000);
  }

  // Register global hotkey
  globalShortcut.register(HOTKEY, () => toggleWindow());

  app.on('activate', () => {
    if (!mainWindow) createWindow();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (pyServer) {
    try {
      if (process.platform === 'win32') {
        // Force kill celého process tree na Windows
        require('child_process').execSync(`taskkill /pid ${pyServer.pid} /T /F`, { stdio: 'ignore' });
      } else {
        pyServer.kill('SIGKILL');
      }
    } catch (e) {
      pyServer.kill();
    }
    pyServer = null;
  }
});

app.on('window-all-closed', () => {
  // Don't quit on macOS, keep in tray
  if (process.platform !== 'darwin') {
    // Do nothing — we keep running in tray
  }
});
