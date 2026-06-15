/**
 * First-run wizard. Secrets are auto-generated (no UI); the user only sets a password.
 * The backend ships a fixed bootstrap admin (admin@lq.ai) and only a reset-admin-password
 * command (no create-user), so the login email is admin@lq.ai — the user can change it
 * later in the app's Settings.
 *
 * NO provider keys are collected here (launcher decision L-3). The stack boots fully
 * healthy with zero provider keys; the user adds an OpenAI/Anthropic key in-app via
 * Configure (BYOK, hot-applied, no restart) — chat needs one key before first use.
 */
const ADMIN_EMAIL = 'admin@lq.ai'

interface Snapshot {
	state: string
	services?: { health: string }[]
}

export function renderWizard(root: HTMLElement, onDone: () => void): void {
	root.innerHTML = `
		<h1>Welcome to LQ.AI</h1>
		<p>LQ.AI runs a private legal-AI workspace on your Mac. This one-time setup sets your
		password and starts the engine. The first start downloads the stack and document-processing
		models and can take several minutes.</p>

		<div class="step">
			<h3>Set your password</h3>
			<p style="margin:4px 0 8px; color:#555">Your login is <strong>${ADMIN_EMAIL}</strong> — you can change it later in Settings → Account.</p>
			<input id="password" type="password" placeholder="Choose a password (12+ characters)" />
		</div>

		<div class="step">
			<p style="color:#555">You'll add an AI provider key (OpenAI or Anthropic) in the app under
			Configure after setup — chat needs one key before first use. No provider key is required to start.</p>
		</div>

		<div class="step">
			<button id="go">Start LQ.AI</button>
			<p id="status"></p>
		</div>
	`

	const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T
	const status = $('status')

	// Live progress while the stack comes up (replaces a static, misleading message).
	window.lqai.onState((snap) => {
		const s = snap as Snapshot
		if (s.state === 'STACK_STARTING') {
			const healthy = (s.services ?? []).filter((x) => x.health === 'healthy').length
			status.style.color = '#555'
			status.textContent = `Starting LQ.AI… ${healthy}/9 services ready (first run pulls images + document-processing models; this can take a few minutes).`
		} else if (s.state === 'NO_ENGINE') {
			status.style.color = '#c00'
			status.textContent = "Docker isn't running — start Docker Desktop and try again."
		}
	})

	$('go').addEventListener('click', async () => {
		const password = $<HTMLInputElement>('password').value

		if (password.length < 12) {
			status.style.color = '#c00'
			status.textContent = 'Choose a password of at least 12 characters.'
			return
		}

		const goBtn = $<HTMLButtonElement>('go')
		goBtn.disabled = true
		status.style.color = '#555'
		status.textContent = 'Starting LQ.AI…'
		const res = await window.lqai.completeWizard({
			adminEmail: ADMIN_EMAIL,
			adminPassword: password
		})
		if (res.ok) onDone()
		else {
			status.style.color = '#c00'
			status.textContent = res.error ?? 'Setup failed.'
			goBtn.disabled = false
		}
	})
}
