import { describe, it, expect } from 'vitest'
import { EXPECTED_SERVICES, DEFAULT_PORTS } from './types'

describe('core constants', () => {
	it('lists all 8 release-stack services (frontend service is "web")', () => {
		expect(EXPECTED_SERVICES).toEqual([
			'postgres',
			'redis',
			'minio',
			'gateway',
			'api',
			'ingest-worker',
			'arq-worker',
			'web'
		])
	})

	it('defaults the web port to the shifted 13012 (distinct from dev + Donna)', () => {
		expect(DEFAULT_PORTS.web).toBe(13012)
	})

	it('uses the full shifted LQ.AI port set', () => {
		expect(DEFAULT_PORTS).toEqual({
			web: 13012,
			api: 18020,
			gateway: 18021,
			postgres: 25442,
			redis: 26389,
			minioApi: 29020,
			minioConsole: 29021
		})
	})
})
