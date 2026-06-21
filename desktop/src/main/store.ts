import { safeStorage } from 'electron'
import { writeFileSync, readFileSync, existsSync, chmodSync, rmSync } from 'node:fs'
import { configPath, envPath } from './paths'
import { renderEnv, ensureMasterKeyLine } from '../core/env'
import { generateMasterKey } from '../core/secrets'
import type { LauncherConfig } from '../core/config'

/** Persist config encrypted at rest via the OS keychain-backed safeStorage. */
export function saveConfig(cfg: LauncherConfig): void {
	const json = Buffer.from(JSON.stringify(cfg), 'utf8')
	// NOTE: LauncherConfig holds the generated stack secrets (Postgres/MinIO/gateway/JWT) —
	// not provider API keys (those are added in-app via Configure / BYOK, never persisted here).
	// safeStorage encrypts at rest via the OS keychain. When encryption is unavailable (rare;
	// headless/CI), we fall back to plaintext JSON — acceptable for those environments, but be
	// aware the generated secrets are then unencrypted.
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

/**
 * Backfill LQ_AI_GATEWAY_MASTER_KEY into an EXISTING install's .env + config.
 *
 * Installs created before the BYOK master key existed have a persisted config and
 * an .env with no master key, so the in-app Provider-keys page returns 400 and the
 * wizard (which writes the key) never re-runs. This runs at launch for non-first-run
 * installs: mints the key if the config lacks it, then appends ONLY the missing line
 * to the .env (append-only — a full renderEnv would wipe a hand-added provider key).
 * No-op on first run (the wizard handles it) and idempotent thereafter. The running
 * gateway picks the key up on its next start/recreate.
 */
export function ensureMasterKey(): void {
	const cfg = loadConfig()
	if (!cfg) return // first run — wizard:complete writes a full .env with the key

	let changed = false
	if (!cfg.secrets.LQ_AI_GATEWAY_MASTER_KEY) {
		cfg.secrets.LQ_AI_GATEWAY_MASTER_KEY = generateMasterKey()
		changed = true
	}

	const path = envPath()
	if (existsSync(path)) {
		const before = readFileSync(path, 'utf8')
		const after = ensureMasterKeyLine(before, cfg.secrets.LQ_AI_GATEWAY_MASTER_KEY)
		if (after !== before) {
			writeFileSync(path, after, { mode: 0o600 })
			chmodSync(path, 0o600)
		}
	}

	if (changed) saveConfig(cfg)
}
