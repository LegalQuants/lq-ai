import { parseEngineProbe } from '../core/engine'
import { parseComposePs, psArgs, upArgs, downArgs, downVArgs, adminFixtureArgs } from '../core/compose'
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

export const startStack = (base: string[], env: NodeJS.ProcessEnv): Promise<RunResult> =>
	runDocker(upArgs(base), env)

export const stopStack = (base: string[]): Promise<RunResult> => runDocker(downArgs(base))

/** Reset: stop the stack AND remove its volumes (wipes all data) for a fresh setup. */
export const resetStack = (base: string[]): Promise<RunResult> => runDocker(downVArgs(base))

export const runAdminFixture = (
	base: string[],
	email: string,
	password: string
): Promise<RunResult> => runDocker(adminFixtureArgs(base, email, password))
