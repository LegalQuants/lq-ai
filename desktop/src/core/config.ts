import type { GeneratedSecrets } from './secrets'
import type { PortConfig } from './types'

export interface LauncherConfig {
	secrets: GeneratedSecrets
	ports: PortConfig
	/** Published image tag to run, e.g. "latest" or "v0.4.0". */
	imageTag: string
	/** GHCR namespace the images live under (default "legalquants"). */
	imageNamespace: string
	adminEmail: string
}

/** First run = no persisted config blob exists yet. */
export function isFirstRun(persisted: LauncherConfig | null): boolean {
	return persisted === null
}
