import { parseEngineProbe } from '../core/engine'
import {
	parseComposePs,
	psArgs,
	pullArgs,
	upArgs,
	downArgs,
	downVArgs,
	adminFixtureArgs
} from '../core/compose'
import { deriveLauncherState } from '../core/state'
import type { LauncherState, ServiceStatus } from '../core/types'
import { runDocker, type RunResult } from './runner'

export interface StackSnapshot {
	state: LauncherState
	services: ServiceStatus[]
	engineMessage?: string
}

type Runner = (args: string[]) => Promise<RunResult>

/** Probe engine + compose ps and derive the snapshot. Runner is injectable for tests. */
export async function snapshot(base: string[], runner: Runner = runDocker): Promise<StackSnapshot> {
	const info = await runner(['info'])
	const engine = parseEngineProbe(info.code, info.stdout, info.stderr)
	if (engine.status !== 'present') {
		return { state: 'NO_ENGINE', services: [], engineMessage: engine.message }
	}
	const ps = await runner(psArgs(base))
	const services = parseComposePs(ps.stdout)
	return { state: deriveLauncherState(engine, services), services }
}

/** Runner that accepts the same (args, env?) shape as {@link runDocker}. */
type StartRunner = (args: string[], env?: NodeJS.ProcessEnv) => Promise<RunResult>

/**
 * Start the stack: refresh images, then bring them up.
 *
 * The `pull` is best-effort. Without it, `up -d` reuses whatever image is
 * already cached for the configured tag (`:latest` by default) and the
 * launcher never picks up a new release — the exact "installed the update but
 * the UI didn't change" trap. `runDocker` never throws, so a failed
 * pull (offline, or a transient registry error) is non-fatal: we ignore its
 * exit code and proceed to `up` with the cached images, so an offline launch
 * still starts the last-known-good stack. When the pull does fetch a newer
 * image, `up -d` recreates the affected containers automatically.
 *
 * The runner is injectable for tests; production uses {@link runDocker}.
 */
export const startStack = async (
	base: string[],
	env: NodeJS.ProcessEnv,
	runner: StartRunner = runDocker
): Promise<RunResult> => {
	await runner(pullArgs(base), env) // best-effort refresh; failure is non-fatal
	return runner(upArgs(base), env)
}

export const stopStack = (base: string[]): Promise<RunResult> => runDocker(downArgs(base))

/** Reset: stop the stack AND remove its volumes (wipes all data) for a fresh setup. */
export const resetStack = (base: string[]): Promise<RunResult> => runDocker(downVArgs(base))

export const runAdminFixture = (
	base: string[],
	email: string,
	password: string
): Promise<RunResult> => runDocker(adminFixtureArgs(base, email, password))
