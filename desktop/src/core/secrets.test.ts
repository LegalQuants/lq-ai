import { describe, it, expect } from 'vitest'
import { generateSecrets } from './secrets'

describe('generateSecrets', () => {
	it('mints all required release-stack secrets', () => {
		const s = generateSecrets()
		expect(Object.keys(s).sort()).toEqual([
			'JWT_SECRET',
			'LQ_AI_GATEWAY_KEY',
			'MINIO_ROOT_PASSWORD',
			'POSTGRES_PASSWORD',
			'S3_SECRET_KEY'
		])
	})

	it('makes S3_SECRET_KEY equal to MINIO_ROOT_PASSWORD (the compose requires the pair to match)', () => {
		const s = generateSecrets()
		expect(s.S3_SECRET_KEY).toBe(s.MINIO_ROOT_PASSWORD)
	})

	it('produces strong values: JWT >= 43 chars, minio password >= 8, no padding/url-unsafe chars', () => {
		const s = generateSecrets()
		expect(s.JWT_SECRET.length).toBeGreaterThanOrEqual(43)
		expect(s.MINIO_ROOT_PASSWORD.length).toBeGreaterThanOrEqual(8)
		for (const v of Object.values(s)) {
			expect(v).toMatch(/^[A-Za-z0-9_-]+$/) // base64url, env-safe (no =, +, /, quotes)
		}
	})

	it('is deterministic given an injected RNG (for reproducible tests)', () => {
		const rng = (n: number) => Buffer.alloc(n, 7)
		expect(generateSecrets(rng)).toEqual(generateSecrets(rng))
	})

	it('is overwhelmingly likely to differ between real calls', () => {
		expect(generateSecrets().JWT_SECRET).not.toBe(generateSecrets().JWT_SECRET)
	})
})
