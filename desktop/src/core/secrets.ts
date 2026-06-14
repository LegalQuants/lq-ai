import { randomBytes } from 'node:crypto'

export interface GeneratedSecrets {
	POSTGRES_PASSWORD: string
	MINIO_ROOT_PASSWORD: string
	/** Must equal MINIO_ROOT_PASSWORD — the release compose pairs them. */
	S3_SECRET_KEY: string
	LQ_AI_GATEWAY_KEY: string
	JWT_SECRET: string
}

/** Injectable RNG so tests can be deterministic; defaults to crypto.randomBytes. */
export type Rng = (n: number) => Buffer

const token = (bytes: number, rng: Rng): string => rng(bytes).toString('base64url')

export function generateSecrets(rng: Rng = randomBytes): GeneratedSecrets {
	const minio = token(18, rng) // 24 base64url chars, well over the 8-char minimum
	return {
		POSTGRES_PASSWORD: token(24, rng),
		MINIO_ROOT_PASSWORD: minio,
		S3_SECRET_KEY: minio,
		LQ_AI_GATEWAY_KEY: token(24, rng),
		JWT_SECRET: token(48, rng) // 64 base64url chars
	}
}
