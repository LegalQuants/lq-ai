import { describe, it, expect } from 'vitest'
import { renderEnv, parseEnv } from './env'
import type { LauncherConfig } from './config'

const base: LauncherConfig = {
	secrets: {
		POSTGRES_PASSWORD: 'pg-secret',
		MINIO_ROOT_PASSWORD: 'minio-secret',
		S3_SECRET_KEY: 'minio-secret',
		LQ_AI_GATEWAY_KEY: 'gw-secret',
		JWT_SECRET: 'jwt-secret'
	},
	ports: {
		web: 13012,
		api: 18020,
		gateway: 18021,
		postgres: 25442,
		redis: 26389,
		minioApi: 29020,
		minioConsole: 29021
	},
	imageTag: 'latest',
	imageNamespace: 'legalquants',
	adminEmail: 'admin@lq.ai'
}

describe('renderEnv', () => {
	it('emits every required secret and the paired S3 key', () => {
		const env = parseEnv(renderEnv(base))
		expect(env.POSTGRES_PASSWORD).toBe('pg-secret')
		expect(env.MINIO_ROOT_PASSWORD).toBe('minio-secret')
		expect(env.S3_SECRET_KEY).toBe('minio-secret')
		expect(env.LQ_AI_GATEWAY_KEY).toBe('gw-secret')
		expect(env.JWT_SECRET).toBe('jwt-secret')
	})

	it('writes the MinIO/S3 user pair the compose defaults read', () => {
		const env = parseEnv(renderEnv(base))
		expect(env.MINIO_ROOT_USER).toBe('lq_ai')
		expect(env.S3_ACCESS_KEY).toBe('lq_ai')
		expect(env.POSTGRES_DB).toBe('lq_ai')
		expect(env.POSTGRES_USER).toBe('lq_ai')
	})

	it('maps every port to the compose host-port var (incl. WEB_HOST_PORT)', () => {
		const env = parseEnv(renderEnv({ ...base, ports: { ...base.ports, web: 14444 } }))
		expect(env.WEB_HOST_PORT).toBe('14444')
		expect(env.API_HOST_PORT).toBe('18020')
		expect(env.GATEWAY_HOST_PORT).toBe('18021')
		expect(env.POSTGRES_HOST_PORT).toBe('25442')
		expect(env.REDIS_HOST_PORT).toBe('26389')
		expect(env.MINIO_API_HOST_PORT).toBe('29020')
		expect(env.MINIO_CONSOLE_HOST_PORT).toBe('29021')
	})

	it('writes the image tag + namespace the compose interpolates', () => {
		const env = parseEnv(renderEnv(base))
		expect(env.LQ_AI_IMAGE_TAG).toBe('latest')
		expect(env.LQ_AI_IMAGE_NAMESPACE).toBe('legalquants')
	})

	it('writes NO provider keys (BYOK in-app, launcher decision L-3)', () => {
		const env = parseEnv(renderEnv(base))
		expect(env.OPENAI_API_KEY).toBeUndefined()
		expect(env.ANTHROPIC_API_KEY).toBeUndefined()
		// And no adapter-node ORIGIN / Ollama leftovers from the Donna template.
		expect(env.ORIGIN).toBeUndefined()
		expect(env.OLLAMA_BASE_URL).toBeUndefined()
	})

	it('emits KEY=VALUE lines whose values carry no whitespace (no newline-injection)', () => {
		const text = renderEnv(base)
		for (const line of text.split('\n')) {
			if (!line || line.startsWith('#')) continue
			expect(line).toMatch(/^[A-Z0-9_]+=\S*$/)
		}
	})
})
