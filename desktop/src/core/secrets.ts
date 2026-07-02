import { randomBytes } from 'node:crypto'

export interface GeneratedSecrets {
	POSTGRES_PASSWORD: string
	MINIO_ROOT_PASSWORD: string
	/** Must equal MINIO_ROOT_PASSWORD — the release compose pairs them. */
	S3_SECRET_KEY: string
	LQ_AI_GATEWAY_KEY: string
	JWT_SECRET: string
	/**
	 * Fernet master key the gateway uses to encrypt runtime BYOK provider keys at rest
	 * (ADR 0011). Without it the gateway's /admin/v1/provider-keys API returns 400
	 * failed_precondition, so the in-app "Provider keys" page can't store anything.
	 * Must be Fernet-format: urlsafe-base64 of 32 random bytes (i.e. padded — carries '=').
	 */
	LQ_AI_GATEWAY_MASTER_KEY: string
}

/** Injectable RNG so tests can be deterministic; defaults to crypto.randomBytes. */
export type Rng = (n: number) => Buffer

const token = (bytes: number, rng: Rng): string => rng(bytes).toString('base64url')

/**
 * A Fernet-compatible key == Python's `Fernet.generate_key()` == urlsafe_b64encode of 32
 * random bytes. Node's 'base64url' strips padding (which Fernet rejects), so emit standard
 * base64 and swap +/ → -_ while KEEPING the '=' padding — byte-identical to the Python form.
 */
const fernetKey = (rng: Rng): string => rng(32).toString('base64').replace(/\+/g, '-').replace(/\//g, '_')

/**
 * Mint a single Fernet master key — used by the first-run wizard (via
 * generateSecrets) and by the launch-time migration that backfills the key into
 * an existing install's .env (so installs predating the BYOK store still work).
 */
export function generateMasterKey(rng: Rng = randomBytes): string {
	return fernetKey(rng)
}

export function generateSecrets(rng: Rng = randomBytes): GeneratedSecrets {
	const minio = token(18, rng) // 24 base64url chars, well over the 8-char minimum
	return {
		POSTGRES_PASSWORD: token(24, rng),
		MINIO_ROOT_PASSWORD: minio,
		S3_SECRET_KEY: minio,
		LQ_AI_GATEWAY_KEY: token(24, rng),
		JWT_SECRET: token(48, rng), // 64 base64url chars
		LQ_AI_GATEWAY_MASTER_KEY: fernetKey(rng)
	}
}
