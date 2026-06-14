import type { EngineProbe } from './types'

/**
 * Interpret the result of `docker info` (or a spawn failure). Pure: the caller does
 * the actual spawn and passes us (exitCode, stdout, stderr). exitCode 127 / ENOENT
 * signals the binary is missing; a daemon-connect error means installed-but-not-running.
 */
export function parseEngineProbe(exitCode: number, stdout: string, stderr: string): EngineProbe {
	if (exitCode === 0) {
		const m = /Server Version:\s*([^\s]+)/.exec(stdout)
		return { status: 'present', version: m?.[1] }
	}

	const err = stderr.toLowerCase()
	if (exitCode === 127 || err.includes('not found') || err.includes('enoent')) {
		return {
			status: 'absent',
			message: 'Docker is not installed. Install Docker Desktop to run LQ.AI.'
		}
	}
	if (err.includes('daemon') || err.includes('docker.sock')) {
		return {
			status: 'error',
			message: 'Docker daemon is not running. Start Docker Desktop and try again.'
		}
	}
	return { status: 'error', message: stderr.trim() || 'Could not reach the Docker engine.' }
}
