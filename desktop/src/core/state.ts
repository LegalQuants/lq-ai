import { EXPECTED_SERVICES } from './types'
import type { EngineProbe, LauncherState, ServiceStatus } from './types'

/**
 * Derive the launcher state from a real engine probe + `docker compose ps` snapshot.
 * Pure and total. Precedence:
 *   1. engine not usable        -> NO_ENGINE
 *   2. any service failed       -> FAILED   (exited / unhealthy)
 *   3. no services at all       -> STOPPED
 *   4. all 8 services healthy   -> HEALTHY
 *   5. otherwise (coming up)    -> STACK_STARTING
 * The "pulling images" and "models downloading" windows are surfaced separately by the
 * orchestrator from command/log signals; they are not decidable from `ps` alone.
 */
export function deriveLauncherState(engine: EngineProbe, services: ServiceStatus[]): LauncherState {
	if (engine.status !== 'present') return 'NO_ENGINE'

	const failed = services.some((s) => s.health === 'exited' || s.health === 'unhealthy')
	if (failed) return 'FAILED'

	if (services.length === 0) return 'STOPPED'

	const healthyNames = new Set(services.filter((s) => s.health === 'healthy').map((s) => s.name))
	const allHealthy = EXPECTED_SERVICES.every((name) => healthyNames.has(name))
	return allHealthy ? 'HEALTHY' : 'STACK_STARTING'
}
