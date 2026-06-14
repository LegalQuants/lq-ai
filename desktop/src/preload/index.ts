import { contextBridge, ipcRenderer } from 'electron'

/** Typed bridge the renderer uses; no Node/Electron exposed beyond these calls. */
const api = {
	isFirstRun: (): Promise<boolean> => ipcRenderer.invoke('config:isFirstRun'),
	completeWizard: (input: unknown): Promise<{ ok: boolean; error?: string }> =>
		ipcRenderer.invoke('wizard:complete', input),
	status: (): Promise<unknown> => ipcRenderer.invoke('stack:status'),
	start: (): Promise<unknown> => ipcRenderer.invoke('stack:start'),
	stop: (): Promise<unknown> => ipcRenderer.invoke('stack:stop'),
	reset: (): Promise<{ ok: boolean; error?: string }> => ipcRenderer.invoke('stack:reset'),
	openWeb: (): Promise<void> => ipcRenderer.invoke('stack:openWeb'),
	installDocker: (): Promise<void> => ipcRenderer.invoke('engine:installDocker'),
	onLog: (cb: (line: string) => void): void => {
		ipcRenderer.on('stack:log', (_e, line: string) => cb(line))
	},
	onState: (cb: (snap: unknown) => void): void => {
		ipcRenderer.on('stack:state', (_e, snap: unknown) => cb(snap))
	}
}

contextBridge.exposeInMainWorld('lqai', api)
export type LqaiBridge = typeof api
