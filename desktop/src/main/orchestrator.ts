import { parseEngineProbe } from '../core/engine'
import {
	parseComposePs,
	psArgs,
	pullArgs,
	upArgs,
	upServicesWaitArgs,
	migrationArgs,
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

export interface MigrationPlan {
	title?: string
	action: 'none' | 'apply' | 'verify' | 'conflict'
	reason: string
	detection: { facts?: Record<string, unknown> }
	checks?: { name: string; passed: boolean; message: string }[]
}

export type ConfirmMigration = (plan: MigrationPlan) => Promise<boolean>
export type MigrationProgress = (message: string) => void

function parseMigrationPlan(stdout: string): MigrationPlan {
	const lines = stdout.trim().split('\n').filter(Boolean)
	for (let index = lines.length - 1; index >= 0; index -= 1) {
		try {
			const value = JSON.parse(lines[index]!) as { plan?: MigrationPlan }
			if (value.plan) return value.plan
		} catch {
			// Compose may prefix informational lines; keep searching from the end.
		}
	}
	throw new Error(`Migration plan returned invalid JSON: ${stdout.slice(-500)}`)
}

function assertSucceeded(result: RunResult, phase: string): void {
	if (result.code !== 0) {
		throw new Error(
			`${phase} failed: ${result.stderr.trim() || result.stdout.trim() || `exit ${result.code}`}`
		)
	}
}

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

/**
 * Start the release stack through ADR 0037's plan → apply → up → verify gate.
 * The Python migration service owns all component logic; Electron only drives
 * Docker and supplies the single required human confirmation.
 */
export const startStackWithMigrations = async (
	base: string[],
	env: NodeJS.ProcessEnv,
	confirm: ConfirmMigration,
	onProgress: MigrationProgress = () => {},
	runner: StartRunner = runDocker
): Promise<RunResult> => {
	await runner(pullArgs(base), env) // still best-effort for offline starts
	// `plan` must inspect an offline volume. `down` preserves every named volume.
	const stopped = await runner(downArgs(base), env)
	assertSucceeded(stopped, 'Stack stop before migration plan')
	onProgress('Checking deployment migrations…')
	const planned = await runner(migrationArgs(base, ['--actor', 'launcher', 'plan', '--json']), env)
	if (![0, 10].includes(planned.code)) {
		throw new Error(
			`Migration plan failed: ${planned.stderr.trim() || planned.stdout.trim() || `exit ${planned.code}`}`
		)
	}
	if (planned.code === 10) {
		const plan = parseMigrationPlan(planned.stdout)
		if (plan.action === 'apply') {
			if (!(await confirm(plan))) {
				await runner(downArgs(base), env)
				return { code: 130, stdout: '', stderr: 'Migration cancelled.' }
			}
			onProgress('Snapshotting the existing object store…')
			const applied = await runner(
				migrationArgs(base, ['--actor', 'launcher', 'apply', '--yes', '--json']),
				env
			)
			assertSucceeded(applied, 'Migration apply')
		}
		if (plan.action === 'apply' || plan.action === 'verify') {
			onProgress('Starting RustFS for verification…')
			const store = await runner(upServicesWaitArgs(base, ['rustfs']), env)
			assertSucceeded(store, 'RustFS start')
			onProgress('Verifying every stored document…')
			const verified = await runner(
				migrationArgs(base, ['--actor', 'launcher', 'verify', '--json']),
				env
			)
			assertSucceeded(verified, 'Migration verify')
		}
	}
	onProgress('Starting LQ.AI…')
	return runner(upArgs(base), env)
}

export const migrationStatus = (
	base: string[],
	env: NodeJS.ProcessEnv,
	runner: StartRunner = runDocker
): Promise<RunResult> =>
	runner(
		migrationArgs(base, ['--actor', 'launcher', 'status', '--json'], {
			noDeps: true
		}),
		env
	)

export const rollbackMigration = async (
	base: string[],
	env: NodeJS.ProcessEnv,
	runner: StartRunner = runDocker
): Promise<RunResult> => {
	const stopped = await runner(downArgs(base), env)
	assertSucceeded(stopped, 'Stack stop before migration rollback')
	return runner(
		migrationArgs(base, ['--actor', 'launcher', 'rollback', '0001', '--yes', '--json'], {
			noDeps: true
		}),
		env
	)
}

export const stopStack = (base: string[]): Promise<RunResult> => runDocker(downArgs(base))

/** Reset: stop the stack AND remove its volumes (wipes all data) for a fresh setup. */
export const resetStack = (base: string[]): Promise<RunResult> => runDocker(downVArgs(base))

export const runAdminFixture = (
	base: string[],
	email: string,
	password: string
): Promise<RunResult> => runDocker(adminFixtureArgs(base, email, password))
