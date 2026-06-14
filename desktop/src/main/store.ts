import { safeStorage } from 'electron'
import { writeFileSync, readFileSync, existsSync, chmodSync, rmSync } from 'node:fs'
import { configPath, envPath } from './paths'
import { renderEnv } from '../core/env'
import type { LauncherConfig } from '../core/config'

/** Persist config encrypted at rest via the OS keychain-backed safeStorage. */
export function saveConfig(cfg: LauncherConfig): void {
	const json = Buffer.from(JSON.stringify(cfg), 'utf8')
	// NOTE: LauncherConfig may include an API key. safeStorage encrypts at rest via the OS
	// keychain. When encryption is unavailable (rare; headless/CI), we fall back to plaintext
	// JSON — acceptable for those environments, but be aware secrets are then unencrypted.
	const blob = safeStorage.isEncryptionAvailable()
		? safeStorage.encryptString(json.toString('utf8'))
		: json
	writeFileSync(configPath(), blob)
}

export function loadConfig(): LauncherConfig | null {
	if (!existsSync(configPath())) return null
	const blob = readFileSync(configPath())
	const json = safeStorage.isEncryptionAvailable() ? safeStorage.decryptString(blob) : blob.toString('utf8')
	return JSON.parse(json) as LauncherConfig
}

/** Delete the persisted config + .env so the next launch re-runs the first-run wizard. */
export function clearConfig(): void {
	for (const p of [configPath(), envPath()]) {
		if (existsSync(p)) rmSync(p)
	}
}

/** Write the chmod-600 .env the compose command reads, into the app data dir. */
export function writeEnvFile(cfg: LauncherConfig): string {
	const path = envPath()
	writeFileSync(path, renderEnv(cfg), { mode: 0o600 })
	chmodSync(path, 0o600) // belt-and-suspenders if the file pre-existed
	return path
}
