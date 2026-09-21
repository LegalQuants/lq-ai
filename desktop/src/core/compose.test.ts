import { describe, it, expect } from 'vitest'
import {
	parseComposePs,
	composeBaseArgs,
	psArgs,
	pullArgs,
	upArgs,
	upServicesWaitArgs,
	migrationArgs,
	downArgs,
	downVArgs,
	logsArgs,
	adminFixtureArgs
} from './compose'

const base = composeBaseArgs('/data/docker-compose.release.yml', 'lq-ai-desktop')

describe('composeBaseArgs', () => {
	it('targets the file and project name', () => {
		expect(base).toEqual([
			'compose',
			'-f',
			'/data/docker-compose.release.yml',
			'-p',
			'lq-ai-desktop'
		])
	})
})

describe('argv builders', () => {
	it('ps requests JSON', () => {
		expect(psArgs(base)).toEqual([...base, 'ps', '--format', 'json'])
	})
	it('pull refreshes images for the configured tag', () => {
		expect(pullArgs(base)).toEqual([...base, 'pull'])
	})
	it('up is detached', () => {
		expect(upArgs(base)).toEqual([...base, 'up', '-d'])
	})
	it('waits for selected services during a migration', () => {
		expect(upServicesWaitArgs(base, ['rustfs'])).toEqual([
			...base,
			'up',
			'-d',
			'--wait',
			'rustfs'
		])
	})
	it('runs the migration CLI through the ops profile without a TTY', () => {
		expect(migrationArgs(base, ['plan', '--json'])).toEqual([
			...base,
			'--profile',
			'ops',
			'run',
			'--rm',
			'-T',
			'migrate',
			'plan',
			'--json'
		])
	})
	it('can read migration status without starting dependencies', () => {
		expect(migrationArgs(base, ['status', '--json'], { noDeps: true })).toContain('--no-deps')
	})
	it('down removes renamed-service orphans but keeps volumes', () => {
		expect(downArgs(base)).toEqual([...base, 'down', '--remove-orphans'])
	})
	it('down -v also removes volumes (Reset)', () => {
		expect(downVArgs(base)).toEqual([...base, 'down', '-v', '--remove-orphans'])
	})
	it('logs follow a single service', () => {
		expect(logsArgs(base, 'web')).toEqual([...base, 'logs', '-f', '--tail', '200', 'web'])
	})
	it('admin fixture runs the CLI in the api container without a TTY', () => {
		expect(adminFixtureArgs(base, 'me@x.com', 'pw123')).toEqual([
			...base,
			'exec',
			'-T',
			'api',
			'python',
			'-m',
			'app.cli',
			'reset-admin-password',
			'--email',
			'me@x.com',
			'--password',
			'pw123',
			'--no-force-change'
		])
	})
})

describe('parseComposePs', () => {
	it('parses JSONL (one object per line — modern docker)', () => {
		const raw =
			'{"Name":"lq-ai-desktop-postgres-1","Service":"postgres","State":"running","Health":"healthy"}\n' +
			'{"Name":"lq-ai-desktop-web-1","Service":"web","State":"running","Health":"starting"}'
		const out = parseComposePs(raw)
		expect(out).toEqual([
			{ name: 'postgres', state: 'running', health: 'healthy' },
			{ name: 'web', state: 'running', health: 'starting' }
		])
	})

	it('parses a JSON array (older docker) too', () => {
		const raw = JSON.stringify([
			{ Service: 'redis', State: 'running', Health: '' },
			{ Service: 'api', State: 'exited', Health: '' }
		])
		const out = parseComposePs(raw)
		expect(out).toEqual([
			{ name: 'redis', state: 'running', health: 'running' },
			{ name: 'api', state: 'exited', health: 'exited' }
		])
	})

	it('maps unhealthy and created states', () => {
		const raw =
			'{"Service":"gateway","State":"running","Health":"unhealthy"}\n' +
			'{"Service":"arq-worker","State":"created","Health":""}'
		expect(parseComposePs(raw)).toEqual([
			{ name: 'gateway', state: 'running', health: 'unhealthy' },
			{ name: 'arq-worker', state: 'created', health: 'created' }
		])
	})

	it('returns [] for empty output (stack never started)', () => {
		expect(parseComposePs('')).toEqual([])
		expect(parseComposePs('   \n')).toEqual([])
	})

	it('skips malformed lines rather than throwing (defensive boundary)', () => {
		const raw = 'not json\n{"Service":"redis","State":"running","Health":"healthy"}'
		expect(parseComposePs(raw)).toEqual([{ name: 'redis', state: 'running', health: 'healthy' }])
	})
})
