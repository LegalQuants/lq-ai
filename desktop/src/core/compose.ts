import type { ServiceHealth, ServiceStatus } from './types'

/** `docker <base...>` — the shared prefix for every compose call. */
export function composeBaseArgs(composeFile: string, projectName: string): string[] {
	return ['compose', '-f', composeFile, '-p', projectName]
}

export const psArgs = (base: string[]): string[] => [...base, 'ps', '--format', 'json']
export const upArgs = (base: string[]): string[] => [...base, 'up', '-d']
export const downArgs = (base: string[]): string[] => [...base, 'down']
/** `down -v` — also removes volumes. Used by Reset to wipe all data for a fresh setup. */
export const downVArgs = (base: string[]): string[] => [...base, 'down', '-v']
export const logsArgs = (base: string[], service: string): string[] => [
	...base,
	'logs',
	'-f',
	'--tail',
	'200',
	service
]

/** First-run admin fixture: create the login the user chose, without a TTY (-T). */
export function adminFixtureArgs(base: string[], email: string, password: string): string[] {
	return [
		...base,
		'exec',
		'-T',
		'api',
		'python',
		'-m',
		'app.cli',
		'reset-admin-password',
		'--email',
		email,
		'--password',
		password,
		'--no-force-change'
	]
}

function mapHealth(state: string, health: string): ServiceHealth {
	if (health === 'healthy' || health === 'starting' || health === 'unhealthy') return health
	switch (state) {
		case 'running':
			return 'running'
		case 'exited':
			return 'exited'
		case 'created':
			return 'created'
		default:
			return 'unknown'
	}
}

interface RawPs {
	Service?: string
	Name?: string
	State?: string
	Health?: string
}

function toStatus(row: RawPs): ServiceStatus | null {
	const name = row.Service ?? row.Name
	if (!name || typeof name !== 'string') return null
	const state = typeof row.State === 'string' ? row.State : 'unknown'
	const health = typeof row.Health === 'string' ? row.Health : ''
	return { name, state, health: mapHealth(state, health) }
}

/**
 * Parse `docker compose ps --format json`. Handles BOTH modern JSONL (one object per
 * line) and the older single JSON array. Drops malformed rows rather than throwing —
 * the same defensive-parser discipline as the app's parseXList helpers.
 */
export function parseComposePs(raw: string): ServiceStatus[] {
	const text = raw.trim()
	if (!text) return []

	// Try whole-string array first.
	try {
		const arr = JSON.parse(text)
		if (Array.isArray(arr)) {
			return arr.map(toStatus).filter((s): s is ServiceStatus => s !== null)
		}
	} catch {
		// fall through to JSONL
	}

	const out: ServiceStatus[] = []
	for (const line of text.split('\n')) {
		const t = line.trim()
		if (!t) continue
		try {
			const row = JSON.parse(t) as RawPs
			const status = toStatus(row)
			if (status) out.push(status)
		} catch {
			// skip malformed line
		}
	}
	return out
}
