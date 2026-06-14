import type { PortConfig } from './types'

export type IsPortFree = (port: number) => boolean

/**
 * Resolve a port map against a free-port predicate. Each service's preferred port
 * is used if free; otherwise we hunt upward to the next free port, and reserve every
 * assigned port so two services never collide. Pure given the injected predicate.
 */
export function resolvePorts(preferred: PortConfig, isFree: IsPortFree): PortConfig {
	const taken = new Set<number>()
	const pick = (want: number): number => {
		let port = want
		// Fail fast rather than hang if a pathological predicate never reports a free port.
		while (taken.has(port) || !isFree(port)) {
			port++
			if (port > want + 1000) throw new Error(`No free port found near ${want}`)
		}
		taken.add(port)
		return port
	}
	// Order matters only for determinism; web first since it's the user-facing one.
	return {
		web: pick(preferred.web),
		api: pick(preferred.api),
		gateway: pick(preferred.gateway),
		postgres: pick(preferred.postgres),
		redis: pick(preferred.redis),
		minioApi: pick(preferred.minioApi),
		minioConsole: pick(preferred.minioConsole)
	}
}
