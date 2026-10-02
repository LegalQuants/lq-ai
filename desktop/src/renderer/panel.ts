interface Snapshot {
	state: string
	services: { name: string; health: string }[]
	engineMessage?: string
}

interface CommandResult {
	code: number
	stdout: string
	stderr: string
}

const LABELS: Record<string, string> = {
	NO_ENGINE: 'Docker is not running',
	STOPPED: 'Stopped',
	STACK_STARTING: 'Starting…',
	HEALTHY: 'Running',
	FAILED: 'Something went wrong'
}

export function renderPanel(root: HTMLElement): void {
	root.innerHTML = `
		<h1>LQ.AI</h1>
		<p>Status: <span class="state" id="state">…</span></p>
		<p id="msg" style="color:#c00"></p>
		<div class="step">
			<button id="open">Open LQ.AI</button>
			<button id="start" class="secondary">Start</button>
			<button id="stop" class="secondary">Stop</button>
			<button id="install" class="secondary" style="display:none">Install Docker Desktop</button>
		</div>
		<h3>Logs</h3>
		<div id="logs"></div>
		<h3>Deployment migrations</h3>
		<pre id="migrations">Loading journal…</pre>
		<button id="rollback" class="secondary">Restore latest migration snapshot…</button>
		<p style="margin-top:24px">
			<button id="reset" class="secondary">Reset…</button>
			<span id="resethint" style="color:#555; margin-left:8px"></span>
		</p>
	`
	const stateEl = document.getElementById('state')!
	const logsEl = document.getElementById('logs')!
	const open = document.getElementById('open') as HTMLButtonElement
	const msgEl = document.getElementById('msg')!
	const install = document.getElementById('install') as HTMLButtonElement
	const reset = document.getElementById('reset') as HTMLButtonElement
	const resetHint = document.getElementById('resethint')!
	const migrationsEl = document.getElementById('migrations')!
	const rollback = document.getElementById('rollback') as HTMLButtonElement

	const refreshMigrations = async (): Promise<void> => {
		const result = (await window.lqai.migrationStatus()) as CommandResult
		if (result.code !== 0) {
			migrationsEl.textContent = result.stderr || 'Migration journal is not available.'
			return
		}
		try {
			const status = JSON.parse(result.stdout.trim()) as {
				entries?: unknown[]
				snapshots?: unknown[]
			}
			migrationsEl.textContent = JSON.stringify(
				{
					entries: (status.entries ?? []).slice(0, 10),
					snapshots: status.snapshots ?? []
				},
				null,
				2
			)
		} catch {
			migrationsEl.textContent = result.stdout || 'Migration journal is empty.'
		}
	}

	const apply = (snap: Snapshot): void => {
		let label = LABELS[snap.state] ?? snap.state
		if (snap.state === 'STACK_STARTING') {
			const healthy = (snap.services ?? []).filter((s) => s.health === 'healthy').length
			label = `Starting… ${healthy}/9 services ready`
		}
		stateEl.textContent = label
		open.disabled = snap.state !== 'HEALTHY'
		const noEngine = snap.state === 'NO_ENGINE'
		msgEl.textContent = noEngine ? (snap.engineMessage ?? '') : ''
		install.style.display = noEngine ? 'inline-block' : 'none'
	}

	document.getElementById('open')!.addEventListener('click', () => window.lqai.openWeb())
	document.getElementById('start')!.addEventListener('click', async () => {
		try {
			await window.lqai.start()
			msgEl.textContent = ''
			tick()
			refreshMigrations()
		} catch (error) {
			msgEl.textContent = `Start failed: ${String(error)}. The migration journal and rollback action are below.`
		}
	})
	document.getElementById('stop')!.addEventListener('click', async () => {
		await window.lqai.stop()
		tick()
	})
	install.addEventListener('click', () => window.lqai.installDocker())
	rollback.addEventListener('click', async () => {
		rollback.disabled = true
		try {
			const result = (await window.lqai.rollbackMigration()) as CommandResult
			msgEl.textContent = result.code === 0 ? 'Snapshot restored.' : result.stderr || result.stdout
			await refreshMigrations()
			await tick()
		} catch (error) {
			msgEl.textContent = `Rollback failed: ${String(error)}`
		} finally {
			rollback.disabled = false
		}
	})

	// Reset wipes the stack + all data and re-runs first-run setup — two-click confirm.
	let resetArmed = false
	reset.addEventListener('click', async () => {
		if (!resetArmed) {
			resetArmed = true
			resetHint.textContent = 'This erases all LQ.AI data on this Mac. Click again to confirm.'
			return
		}
		reset.disabled = true
		resetHint.textContent = 'Resetting…'
		const res = await window.lqai.reset()
		if (res.ok) window.location.reload()
		else {
			reset.disabled = false
			resetArmed = false
			resetHint.textContent = res.error ?? 'Reset failed.'
		}
	})

	const MAX_LOG_LINES = 2000
	window.lqai.onLog((line) => {
		const lines = (logsEl.textContent + line + '\n').split('\n')
		if (lines.length > MAX_LOG_LINES) lines.splice(0, lines.length - MAX_LOG_LINES)
		logsEl.textContent = lines.join('\n')
		logsEl.scrollTop = logsEl.scrollHeight
	})
	window.lqai.onState((snap) => apply(snap as Snapshot))

	const tick = async (): Promise<void> => {
		const snap = (await window.lqai.status()) as Snapshot
		if (snap) apply(snap)
	}
	tick()
	refreshMigrations()
	setInterval(tick, 5000)
}
