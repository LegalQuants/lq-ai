/** Names of every service in docker-compose.release.yml, in dependency-ish order. */
export const EXPECTED_SERVICES = [
	'postgres',
	'redis',
	'minio',
	'gateway',
	'api',
	'ingest-worker',
	'arq-worker',
	'web',
	// The reverse proxy owns the user-facing WEB_HOST_PORT and unifies the
	// origin: it strips /lq and forwards the lq-ai client's /lq/api/v1/* calls
	// to the api, while everything else (the OpenWebUI shell, /api/config, its
	// own /api/v1/*, websockets, static) stays on web. Last in the dependency
	// order: it depends on both api + web being healthy.
	'proxy'
] as const

export type ServiceName = (typeof EXPECTED_SERVICES)[number]

export interface PortConfig {
	web: number
	api: number
	gateway: number
	postgres: number
	redis: number
	minioApi: number
	minioConsole: number
}

/**
 * Shifted defaults matching .env.release.example so the LQ.AI launcher coexists with
 * BOTH the build-from-source dev stack AND a Donna launcher on one Mac.
 */
export const DEFAULT_PORTS: PortConfig = {
	web: 13012,
	api: 18020,
	gateway: 18021,
	postgres: 25442,
	redis: 26389,
	minioApi: 29020,
	minioConsole: 29021
}

export type EngineStatus = 'absent' | 'present' | 'error'

export interface EngineProbe {
	status: EngineStatus
	version?: string
	message?: string
}

export type ServiceHealth =
	| 'healthy'
	| 'starting'
	| 'unhealthy'
	| 'running'
	| 'exited'
	| 'created'
	| 'unknown'

export interface ServiceStatus {
	name: string
	state: string
	health: ServiceHealth
}

export type LauncherState =
	| 'NO_ENGINE'
	| 'STACK_STARTING'
	| 'HEALTHY'
	| 'STOPPED'
	| 'FAILED'
