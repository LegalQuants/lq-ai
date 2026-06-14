import { describe, it, expect } from 'vitest'
import { parseEngineProbe } from './engine'

describe('parseEngineProbe', () => {
	it('present when `docker info` exits 0', () => {
		const probe = parseEngineProbe(0, 'Server Version: 27.0.3\n', '')
		expect(probe.status).toBe('present')
		expect(probe.version).toBe('27.0.3')
	})

	it('absent when the docker binary is missing (ENOENT-style)', () => {
		const probe = parseEngineProbe(127, '', 'command not found: docker')
		expect(probe.status).toBe('absent')
		expect(probe.message).toMatch(/not found|install/i)
	})

	it('error when docker exists but the daemon is not reachable', () => {
		const probe = parseEngineProbe(
			1,
			'',
			'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?'
		)
		expect(probe.status).toBe('error')
		expect(probe.message).toMatch(/daemon/i)
	})
})
