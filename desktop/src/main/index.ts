import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { join } from 'node:path'
import { composeBaseArgs, logsArgs } from '../core/compose'
import { resolvePorts } from '../core/ports'
import { generateSecrets } from '../core/secrets'
import { DEFAULT_PORTS } from '../core/types'
import type { LauncherConfig } from '../core/config'
import { loadConfig, saveConfig, writeEnvFile, clearConfig } from './store'
import { composeFilePath, envPath, PROJECT_NAME } from './paths'
import {
	snapshot,
	startStack,
	stopStack,
	resetStack,
	runAdminFixture,
	type StackSnapshot
} from './orchestrator'
import { streamDocker } from './runner'
import { isPortFreeSync } from './netcheck'

let win: BrowserWindow | null = null

/** Compose base args, including the app-data --env-file so the generated .env is used. */
const base = (): string[] => [...composeBaseArgs(composeFilePath(), PROJECT_NAME), '--env-file', envPath()]

interface WizardInput {
	adminEmail: string
	adminPassword: string
}

function createWindow(): void {
	win = new BrowserWindow({
		width: 1100,
		height: 760,
		webPreferences: {
			preload: join(__dirname, '../preload/index.mjs'),
			// contextIsolation stays on (Electron default) — the security boundary.
			// sandbox is false because electron-vite emits an ESM preload (.mjs), which
			// sandboxed preloads cannot load. contextIsolation (on) is the real boundary.
			sandbox: false
		}
	})
	if (process.env.ELECTRON_RENDERER_URL) win.loadURL(process.env.ELECTRON_RENDERER_URL)
	else win.loadFile(join(__dirname, '../renderer/index.html'))
}

async function waitHealthy(b: string[], timeoutMs = 600_000): Promise<void> {
	const started = Date.now()
	while (Date.now() - started < timeoutMs) {
		const snap: StackSnapshot = await snapshot(b)
		win?.webContents.send('stack:state', snap)
		if (snap.state === 'HEALTHY') return
		if (snap.state === 'FAILED') throw new Error('Stack failed to start; see logs.')
		if (snap.state === 'NO_ENGINE')
			throw new Error(snap.engineMessage ?? "Docker isn't running. Start Docker Desktop and try again.")
		await new Promise((r) => setTimeout(r, 4000))
	}
	throw new Error('Timed out waiting for the stack to become healthy.')
}

ipcMain.handle('config:isFirstRun', () => loadConfig() === null)

ipcMain.handle('wizard:complete', async (_e, input: WizardInput) => {
	try {
		if (typeof input?.adminEmail !== 'string' || typeof input?.adminPassword !== 'string') {
			return { ok: false, error: 'Invalid setup input.' }
		}
		const cfg: LauncherConfig = {
			secrets: generateSecrets(),
			ports: resolvePorts(DEFAULT_PORTS, isPortFreeSync),
			// Default to the floating "latest" tag for now; Kevin pins a real version
			// (e.g. v0.4.0) when cutting a release. Namespace is overridable for forks/mirrors.
			imageTag: 'latest',
			imageNamespace: 'legalquants',
			adminEmail: input.adminEmail
		}
		// Write the .env (needed before startStack) but DON'T persist the config blob yet —
		// only mark the wizard complete after the stack is healthy and the admin exists, so a
		// failed first run re-shows the wizard instead of stranding a half-configured install.
		writeEnvFile(cfg)
		const b = base()
		await startStack(b, process.env)
		await waitHealthy(b)
		const admin = await runAdminFixture(b, input.adminEmail, input.adminPassword)
		if (admin.code !== 0) {
			throw new Error(
				`Could not set up the login: ${admin.stderr.trim() || admin.stdout.trim() || 'admin fixture failed'}`
			)
		}
		saveConfig(cfg)
		return { ok: true }
	} catch (err) {
		return { ok: false, error: String(err) }
	}
})

ipcMain.handle('stack:status', () => snapshot(base()))
ipcMain.handle('stack:start', () => startStack(base(), process.env))
ipcMain.handle('stack:stop', () => stopStack(base()))
ipcMain.handle('stack:openWeb', () => {
	const cfg = loadConfig()
	const port = cfg?.ports.web ?? DEFAULT_PORTS.web
	win?.loadURL(`http://localhost:${port}`)
})
// Reset: stop the stack, remove its volumes (down -v), and delete the stored config/.env
// so the next launch re-runs the first-run wizard. down -v runs while .env still exists.
ipcMain.handle('stack:reset', async () => {
	try {
		await resetStack(base())
		clearConfig()
		return { ok: true }
	} catch (err) {
		return { ok: false, error: String(err) }
	}
})
ipcMain.handle('engine:installDocker', () =>
	// Direct Apple-Silicon Docker Desktop download (this launcher is arm64-only).
	shell.openExternal('https://desktop.docker.com/mac/main/arm64/Docker.dmg')
)

app.whenReady().then(() => {
	createWindow()
	// Tail web logs into the renderer (best-effort; ignored before the stack exists).
	const stopLogTail = streamDocker(logsArgs(base(), 'web'), (line) =>
		win?.webContents.send('stack:log', line)
	)
	app.on('before-quit', stopLogTail)
})

app.on('window-all-closed', () => {
	if (process.platform !== 'darwin') app.quit()
})
