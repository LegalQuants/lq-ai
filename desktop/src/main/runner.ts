import { spawn } from 'node:child_process'
import { dockerSearchPath } from '../core/dockerPath'

export interface RunResult {
	code: number
	stdout: string
	stderr: string
}

/**
 * Env for spawning `docker`. A Finder-launched macOS app inherits a minimal PATH that
 * omits /usr/local/bin (where Docker Desktop's CLI lives), so a bare spawn ENOENTs even
 * with Docker installed. Augment PATH with the known docker bin dirs.
 */
function dockerSpawnEnv(extra?: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
	return { ...process.env, ...extra, PATH: dockerSearchPath(process.env.PATH) }
}

/** Run `docker <args>` to completion, capturing output. Never throws on non-zero. */
export function runDocker(args: string[], env?: NodeJS.ProcessEnv): Promise<RunResult> {
	return new Promise((resolve) => {
		const child = spawn('docker', args, { env: dockerSpawnEnv(env) })
		let stdout = ''
		let stderr = ''
		child.stdout.on('data', (d) => (stdout += d.toString()))
		child.stderr.on('data', (d) => (stderr += d.toString()))
		child.on('error', (err) => resolve({ code: 127, stdout, stderr: stderr + String(err) }))
		child.on('close', (code) => resolve({ code: code ?? 1, stdout, stderr }))
	})
}

/** Stream `docker <args>` lines to a callback (for `logs -f`). Returns a kill fn. */
export function streamDocker(args: string[], onLine: (line: string) => void): () => void {
	const child = spawn('docker', args, { env: dockerSpawnEnv() })
	const pump = (buf: Buffer) => buf.toString().split('\n').forEach((l) => l && onLine(l))
	child.stdout.on('data', pump)
	child.stderr.on('data', pump)
	// Best-effort: a spawn failure (e.g. docker not found, or the stack not up yet) must
	// NOT crash the main process — the engine/stack state is reported via runDocker instead.
	child.on('error', () => {})
	return () => child.kill()
}
