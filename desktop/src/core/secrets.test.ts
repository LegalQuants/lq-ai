import { describe, it, expect } from 'vitest'
import { generateSecrets, generateMasterKey } from './secrets'

describe('generateSecrets', () => {
	it('mints all required release-stack secrets', () => {
		const s = generateSecrets()
		expect(Object.keys(s).sort()).toEqual([
			'JWT_SECRET',
			'LQ_AI_GATEWAY_KEY',
			'LQ_AI_GATEWAY_MASTER_KEY',
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
		// The master key is Fernet-format (padded base64) so it carries one '='; check it
		// separately below. Every other secret is bare base64url (env-safe, no padding).
		for (const [k, v] of Object.entries(s)) {
			if (k === 'LQ_AI_GATEWAY_MASTER_KEY') continue
			expect(v).toMatch(/^[A-Za-z0-9_-]+$/) // base64url, env-safe (no =, +, /, quotes)
		}
	})

	it('mints a Fernet-format master key: 32-byte urlsafe-base64 (44 chars, single padding)', () => {
		const key = generateSecrets().LQ_AI_GATEWAY_MASTER_KEY
		// Fernet.generate_key() == urlsafe_b64encode(32 random bytes): 43 urlsafe chars + '='.
		expect(key).toMatch(/^[A-Za-z0-9_-]{43}=$/)
		// Decodes to exactly 32 bytes (what cryptography's Fernet requires).
		const decoded = Buffer.from(key.replace(/-/g, '+').replace(/_/g, '/'), 'base64')
		expect(decoded.length).toBe(32)
	})

	it('is deterministic given an injected RNG (for reproducible tests)', () => {
		const rng = (n: number) => Buffer.alloc(n, 7)
		expect(generateSecrets(rng)).toEqual(generateSecrets(rng))
	})

	it('is overwhelmingly likely to differ between real calls', () => {
		expect(generateSecrets().JWT_SECRET).not.toBe(generateSecrets().JWT_SECRET)
	})
})

describe('generateMasterKey', () => {
	it('mints a Fernet-format key (44 chars, decodes to 32 bytes) matching the wizard secret', () => {
		const key = generateMasterKey()
		expect(key).toMatch(/^[A-Za-z0-9_-]{43}=$/)
		expect(Buffer.from(key.replace(/-/g, '+').replace(/_/g, '/'), 'base64').length).toBe(32)
	})

	it('differs between real calls', () => {
		expect(generateMasterKey()).not.toBe(generateMasterKey())
	})
})
