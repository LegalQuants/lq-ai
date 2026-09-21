import { describe, it, expect } from 'vitest'
import { rollbackMigration, snapshot, startStack, startStackWithMigrations } from './orchestrator'

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
			'{"Service":"rustfs","State":"running","Health":"healthy"}\n' +
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

describe('startStack', () => {
	const base = ['compose', '-f', 'x', '-p', 'lq-ai-desktop']

	it('pulls images before bringing the stack up', async () => {
		const calls: string[][] = []
		const runner = async (args: string[]) => {
			calls.push(args)
			return { code: 0, stdout: '', stderr: '' }
		}
		await startStack(base, {}, runner)
		expect(calls).toEqual([
			[...base, 'pull'],
			[...base, 'up', '-d']
		])
	})

	it('still brings the stack up when the pull fails (offline)', async () => {
		const calls: string[][] = []
		// runDocker never throws — a failed pull resolves with a non-zero code.
		const runner = async (args: string[]) => {
			calls.push(args)
			const failed = args.includes('pull')
			return {
				code: failed ? 1 : 0,
				stdout: '',
				stderr: failed ? 'no network' : ''
			}
		}
		const result = await startStack(base, {}, runner)
		expect(calls.map((c) => c[c.length - 1])).toEqual(['pull', '-d'])
		expect(result.code).toBe(0) // the `up` result is returned, not the pull's
	})
})

describe('startStackWithMigrations', () => {
	const base = ['compose', '-f', 'x', '-p', 'lq-ai-desktop']

	it('starts normally when plan reports nothing pending', async () => {
		const calls: string[][] = []
		const runner = async (args: string[]) => {
			calls.push(args)
			if (args.includes('plan'))
				return { code: 0, stdout: '{"plan":{"action":"none"}}', stderr: '' }
			return { code: 0, stdout: '', stderr: '' }
		}
		await startStackWithMigrations(
			base,
			{},
			async () => true,
			() => {},
			runner
		)
		expect(calls.some((call) => call.includes('plan'))).toBe(true)
		expect(calls.at(-1)).toEqual([...base, 'up', '-d'])
	})

	it('confirms, applies, starts RustFS, verifies, then starts the stack', async () => {
		const calls: string[][] = []
		let confirmed = false
		const runner = async (args: string[]) => {
			calls.push(args)
			if (args.includes('plan')) {
				return {
					code: 10,
					stdout: '{"plan":{"action":"apply","reason":"upgrade","detection":{"facts":{}}}}',
					stderr: ''
				}
			}
			return { code: 0, stdout: '{}', stderr: '' }
		}
		await startStackWithMigrations(
			base,
			{},
			async () => {
				confirmed = true
				return true
			},
			() => {},
			runner
		)
		expect(confirmed).toBe(true)
		expect(calls.some((call) => call.includes('apply'))).toBe(true)
		expect(calls.some((call) => call.includes('rustfs') && call.includes('--wait'))).toBe(true)
		expect(calls.some((call) => call.includes('verify'))).toBe(true)
		expect(calls.at(-1)).toEqual([...base, 'up', '-d'])
	})

	it('stops dependency containers again when the user cancels', async () => {
		const calls: string[][] = []
		const runner = async (args: string[]) => {
			calls.push(args)
			if (args.includes('plan')) {
				return {
					code: 10,
					stdout: '{"plan":{"action":"apply","reason":"upgrade","detection":{"facts":{}}}}',
					stderr: ''
				}
			}
			return { code: 0, stdout: '', stderr: '' }
		}
		const result = await startStackWithMigrations(
			base,
			{},
			async () => false,
			() => {},
			runner
		)
		expect(result.code).toBe(130)
		expect(calls.filter((call) => call.includes('down'))).toHaveLength(2)
	})
})

describe('rollbackMigration', () => {
	it('stops the stack and restores migration 0001 without starting dependencies', async () => {
		const base = ['compose', '-f', 'x', '-p', 'lq-ai-desktop']
		const calls: string[][] = []
		const runner = async (args: string[]) => {
			calls.push(args)
			return { code: 0, stdout: '{}', stderr: '' }
		}
		await rollbackMigration(base, {}, runner)
		expect(calls[0]).toEqual([...base, 'down'])
		expect(calls[1]).toContain('--no-deps')
		expect(calls[1]).toContain('rollback')
	})
})
