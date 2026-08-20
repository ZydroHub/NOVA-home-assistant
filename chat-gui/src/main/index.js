import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'

// On Linux (e.g. Raspberry Pi), Chromium may log "GLib-GObject: instance has no handler with id"
// when the UI updates (e.g. after deleting a task). These come from content/browser and are harmless.
// To reduce stderr noise you can run with: ELECTRON_DISABLE_GPU=1 (may affect performance).

// Enable touch events so finger scroll works on touchscreens (e.g. 4.3" display)
app.commandLine.appendSwitch('enable-touch-events')

function createWindow() {
    const mainWindow = new BrowserWindow({
        width: 480,
        height: 800,
        fullscreen: true,
        frame: false,
        show: false,
        autoHideMenuBar: true,
        webPreferences: {
            preload: join(__dirname, '../preload/index.mjs'),
            sandbox: false
        }
    })

    mainWindow.on('ready-to-show', () => {
        mainWindow.show()
    })

    mainWindow.webContents.setWindowOpenHandler((details) => {
        shell.openExternal(details.url)
        return { action: 'deny' }
    })

    // HMR for renderer base on electron-vite CLI.
    // Load the remote URL for development or the local html file for production.
    if (process.env['ELECTRON_RENDERER_URL']) {
        mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
    } else {
        mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
    }
}

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
    // Set app user model id for windows
    // electronApp.setAppUserModelId('com.electron')

    ipcMain.on('app-quit', () => app.quit())

    createWindow()

    app.on('activate', function () {
        // On macOS it's common to re-create a window in the app when the
        // dock icon is clicked and there are no other windows open.
        if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
})
