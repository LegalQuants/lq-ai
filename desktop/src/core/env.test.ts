import { describe, it, expect } from 'vitest'
import { renderEnv, parseEnv, providerKeyVar, ensureMasterKeyLine } from './env'
import type { LauncherConfig } from './config'

const base: LauncherConfig = {
	secrets: {
		POSTGRES_PASSWORD: 'pg-secret',
		MINIO_ROOT_PASSWORD: 'minio-secret',
		S3_SECRET_KEY: 'minio-secret',
		LQ_AI_GATEWAY_KEY: 'gw-secret',
		JWT_SECRET: 'jwt-secret',
		LQ_AI_GATEWAY_MASTER_KEY: 'master-key-fernet='
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
		// Forwarded so the gateway's runtime BYOK provider-key store is enabled.
		expect(env.LQ_AI_GATEWAY_MASTER_KEY).toBe('master-key-fernet=')
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

	it('writes NO provider key when the wizard collected none (stack boots keyless)', () => {
		const env = parseEnv(renderEnv(base))
		expect(env.OPENAI_API_KEY).toBeUndefined()
		expect(env.ANTHROPIC_API_KEY).toBeUndefined()
		// And no adapter-node ORIGIN / Ollama leftovers from the Donna template.
		expect(env.ORIGIN).toBeUndefined()
		expect(env.OLLAMA_BASE_URL).toBeUndefined()
	})

	it('writes ANTHROPIC_API_KEY for an sk-ant- key and no OpenAI var', () => {
		const env = parseEnv(renderEnv({ ...base, providerKey: 'sk-ant-api03-abc123' }))
		expect(env.ANTHROPIC_API_KEY).toBe('sk-ant-api03-abc123')
		expect(env.OPENAI_API_KEY).toBeUndefined()
	})

	it('writes OPENAI_API_KEY for a non-Anthropic key (sk-proj / sk-) and no Anthropic var', () => {
		const env = parseEnv(renderEnv({ ...base, providerKey: 'sk-proj-xyz789' }))
		expect(env.OPENAI_API_KEY).toBe('sk-proj-xyz789')
		expect(env.ANTHROPIC_API_KEY).toBeUndefined()
	})

	it('trims surrounding whitespace from a pasted key', () => {
		const env = parseEnv(renderEnv({ ...base, providerKey: '  sk-ant-trimmed  \n' }))
		expect(env.ANTHROPIC_API_KEY).toBe('sk-ant-trimmed')
	})

	it('writes no provider key for an empty/whitespace-only field', () => {
		const env = parseEnv(renderEnv({ ...base, providerKey: '   ' }))
		expect(env.ANTHROPIC_API_KEY).toBeUndefined()
		expect(env.OPENAI_API_KEY).toBeUndefined()
	})

	it('drops a malformed key that contains internal whitespace (no corrupt .env line)', () => {
		const env = parseEnv(renderEnv({ ...base, providerKey: 'sk-ant-aaa bbb' }))
		expect(env.ANTHROPIC_API_KEY).toBeUndefined()
		expect(env.OPENAI_API_KEY).toBeUndefined()
	})

	it('emits KEY=VALUE lines whose values carry no whitespace (no newline-injection)', () => {
		const text = renderEnv({ ...base, providerKey: 'sk-ant-with-key' })
		for (const line of text.split('\n')) {
			if (!line || line.startsWith('#')) continue
			expect(line).toMatch(/^[A-Z0-9_]+=\S*$/)
		}
	})
})

describe('ensureMasterKeyLine', () => {
	it('appends the key when missing, preserving existing lines (e.g. a hand-added provider key)', () => {
		const before = 'LQ_AI_GATEWAY_KEY=gw\nANTHROPIC_API_KEY=sk-ant-manual\n'
		const after = parseEnv(ensureMasterKeyLine(before, 'master-abc='))
		expect(after.LQ_AI_GATEWAY_MASTER_KEY).toBe('master-abc=')
		expect(after.ANTHROPIC_API_KEY).toBe('sk-ant-manual') // preserved
		expect(after.LQ_AI_GATEWAY_KEY).toBe('gw') // preserved
	})

	it('is idempotent — leaves text unchanged when the key already exists', () => {
		const text = 'LQ_AI_GATEWAY_MASTER_KEY=already=\nFOO=bar\n'
		expect(ensureMasterKeyLine(text, 'new-key=')).toBe(text)
	})

	it('inserts a separating newline when the file does not end in one', () => {
		const out = ensureMasterKeyLine('FOO=bar', 'mk=')
		expect(out).toBe('FOO=bar\nLQ_AI_GATEWAY_MASTER_KEY=mk=\n')
	})
})

describe('providerKeyVar', () => {
	it('routes sk-ant- keys to ANTHROPIC_API_KEY (case-insensitive prefix)', () => {
		expect(providerKeyVar('sk-ant-api03-abc')).toBe('ANTHROPIC_API_KEY')
		expect(providerKeyVar('SK-ANT-loud')).toBe('ANTHROPIC_API_KEY')
	})

	it('routes everything else to OPENAI_API_KEY', () => {
		expect(providerKeyVar('sk-proj-abc')).toBe('OPENAI_API_KEY')
		expect(providerKeyVar('sk-abc')).toBe('OPENAI_API_KEY')
	})
})
