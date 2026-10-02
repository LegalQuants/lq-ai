import type { GeneratedSecrets } from './secrets'
import type { PortConfig } from './types'

export interface LauncherConfig {
	secrets: GeneratedSecrets
	ports: PortConfig
	/** Published image tag baked into this launcher release. */
	imageTag: string
	/** GHCR namespace the images live under (default "legalquants"). */
	imageNamespace: string
	adminEmail: string
	/**
	 * Optional provider API key collected by the first-run wizard (launcher decision
	 * L-3, revised). Written to .env as ANTHROPIC_API_KEY or OPENAI_API_KEY depending
	 * on its prefix; omitted/blank leaves the stack keyless (boots healthy, chat
	 * answers only once a key is supplied). Not persisted to the encrypted config blob.
	 */
	providerKey?: string
}

/** First run = no persisted config blob exists yet. */
export function isFirstRun(persisted: LauncherConfig | null): boolean {
	return persisted === null
}
