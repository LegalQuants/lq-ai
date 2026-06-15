import { describe, it, expect } from 'vitest'
import { snapshot } from './orchestrator'

// Inject a fake runner so this stays a pure unit test (no real docker).
function fakeRunner(map: Record<string, { code: number; stdout: string; stderr: string }>) {
	return async (args: string[]): Promise<{ code: number; stdout: string; stderr: string }> => {
		if (args.includes('info')) return map['info']!
		if (args.includes('ps')) return map['ps']!
		return { code: 0, stdout: '', stderr: '' }
	}
}

describe('snapshot', () => {
	it('reports HEALTHY when info ok and all services healthy', async () => {
		const ps =
			'{"Service":"postgres","State":"running","Health":"healthy"}\n' +
			'{"Service":"redis","State":"running","Health":"healthy"}\n' +
			'{"Service":"minio","State":"running","Health":"healthy"}\n' +
			'{"Service":"gateway","State":"running","Health":"healthy"}\n' +
			'{"Service":"api","State":"running","Health":"healthy"}\n' +
			'{"Service":"ingest-worker","State":"running","Health":"healthy"}\n' +
			'{"Service":"arq-worker","State":"running","Health":"healthy"}\n' +
			'{"Service":"web","State":"running","Health":"healthy"}\n' +
				'{"Service":"proxy","State":"running","Health":"healthy"}'
		const runner = fakeRunner({
			info: { code: 0, stdout: 'Server Version: 27.0.3', stderr: '' },
			ps: { code: 0, stdout: ps, stderr: '' }
		})
		const snap = await snapshot(['compose', '-f', 'x', '-p', 'lq-ai-desktop'], runner)
		expect(snap.state).toBe('HEALTHY')
		expect(snap.services).toHaveLength(9)
	})

	it('reports NO_ENGINE when docker info fails', async () => {
		const runner = fakeRunner({
			info: { code: 127, stdout: '', stderr: 'not found' },
			ps: { code: 1, stdout: '', stderr: '' }
		})
		const snap = await snapshot(['compose', '-f', 'x', '-p', 'lq-ai-desktop'], runner)
		expect(snap.state).toBe('NO_ENGINE')
	})
})
