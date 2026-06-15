import { describe, it, expect } from 'vitest'
import { deriveLauncherState } from './state'
import { EXPECTED_SERVICES } from './types'
import type { EngineProbe, ServiceStatus } from './types'

const present: EngineProbe = { status: 'present', version: '27.0.3' }

function allHealthy(): ServiceStatus[] {
	return EXPECTED_SERVICES.map((name) => ({ name, state: 'running', health: 'healthy' }))
}

describe('deriveLauncherState', () => {
	it('NO_ENGINE when the engine is absent (regardless of stale service data)', () => {
		expect(deriveLauncherState({ status: 'absent' }, [])).toBe('NO_ENGINE')
	})

	it('NO_ENGINE when the engine errors (daemon down)', () => {
		expect(deriveLauncherState({ status: 'error', message: 'daemon down' }, [])).toBe('NO_ENGINE')
	})

	it('STOPPED when the engine is up but no services exist', () => {
		expect(deriveLauncherState(present, [])).toBe('STOPPED')
	})

	it('HEALTHY only when all 9 services are healthy', () => {
		expect(deriveLauncherState(present, allHealthy())).toBe('HEALTHY')
	})

	it('STACK_STARTING when the proxy is still coming up (others healthy)', () => {
		const services = allHealthy()
		services[8] = { name: 'proxy', state: 'running', health: 'starting' }
		expect(deriveLauncherState(present, services)).toBe('STACK_STARTING')
	})

	it('STACK_STARTING when some services are present but not all healthy', () => {
		const services = allHealthy()
		services[7] = { name: 'web', state: 'running', health: 'starting' }
		expect(deriveLauncherState(present, services)).toBe('STACK_STARTING')
	})

	it('STACK_STARTING when only some of the 9 services have come up yet', () => {
		const partial = allHealthy().slice(0, 3)
		expect(deriveLauncherState(present, partial)).toBe('STACK_STARTING')
	})

	it('FAILED when any service has exited', () => {
		const services = allHealthy()
		services[4] = { name: 'api', state: 'exited', health: 'exited' }
		expect(deriveLauncherState(present, services)).toBe('FAILED')
	})

	it('FAILED when any service is unhealthy', () => {
		const services = allHealthy()
		services[3] = { name: 'gateway', state: 'running', health: 'unhealthy' }
		expect(deriveLauncherState(present, services)).toBe('FAILED')
	})
})
