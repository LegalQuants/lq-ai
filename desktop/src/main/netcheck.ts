/**
 * Best-effort free-port predicate used once at wizard time. It currently always reports
 * "free": a truly reliable check is async, and a genuine bind clash surfaces later as a
 * FAILED stack state (which the UI reports honestly). resolvePorts also guards against a
 * runaway scan. A blocking async pre-check is a Phase 3 refinement (resource controls).
 */
export function isPortFreeSync(_port: number): boolean {
	return true
}
