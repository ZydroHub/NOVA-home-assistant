import { contextBridge, ipcRenderer } from 'electron'

const electronAPI = {
    quit: () => ipcRenderer.send('app-quit')
}

if (process.contextIsolated) {
    try {
        contextBridge.exposeInMainWorld('electron', electronAPI)
    } catch (error) {
        console.error(error)
    }
} else {
    window.electron = electronAPI
}
