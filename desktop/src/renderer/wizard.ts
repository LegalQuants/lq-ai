/**
 * First-run wizard. Secrets are auto-generated (no UI); the user only sets a password.
 * The backend ships a fixed bootstrap admin (admin@lq.ai) and only a reset-admin-password
 * command (no create-user), so the login email is admin@lq.ai — the user can change it
 * later in the app's Settings.
 *
 * An OPTIONAL provider key is collected here (launcher decision L-3, revised): the stack
 * boots fully healthy with zero provider keys, but chat can't answer until one is present
 * and the shipped launcher has no in-app key-entry page. So the wizard offers one optional
 * field — paste an Anthropic (sk-ant-…) or OpenAI key and chat works on first use; leave it
 * blank to start keyless and supply a key later by editing the .env. The provider is
 * auto-detected from the key prefix (see core/env.ts providerKeyVar).
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
			<h3>AI provider key <span style="font-weight:normal; color:#888">(optional)</span></h3>
			<p style="margin:4px 0 8px; color:#555">Paste an Anthropic (<code>sk-ant-…</code>) or OpenAI key so chat
			works right away. You can leave this blank to start — the engine runs without it — and add a key later.</p>
			<input id="providerKey" type="password" placeholder="sk-ant-… or sk-… (optional)" autocomplete="off" />
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
		const providerKey = $<HTMLInputElement>('providerKey').value.trim()

		if (password.length < 12) {
			status.style.color = '#c00'
			status.textContent = 'Choose a password of at least 12 characters.'
			return
		}

		// Optional, but if supplied it must be a single token — catch the fat-fingered
		// paste here rather than silently dropping it in renderEnv.
		if (providerKey && /\s/.test(providerKey)) {
			status.style.color = '#c00'
			status.textContent = 'That API key contains a space — paste just the key (no quotes or extra text).'
			return
		}
		// Both Anthropic (sk-ant-…) and OpenAI (sk-… / sk-proj-…) keys start with "sk-".
		// Reject anything else so a wrong paste isn't silently filed under OpenAI.
		if (providerKey && !providerKey.startsWith('sk-')) {
			status.style.color = '#c00'
			status.textContent =
				'That doesn’t look like an Anthropic or OpenAI key (they start with "sk-"). Check the value, or leave it blank and add a key later.'
			return
		}

		const goBtn = $<HTMLButtonElement>('go')
		goBtn.disabled = true
		status.style.color = '#555'
		status.textContent = 'Starting LQ.AI…'
		const res = await window.lqai.completeWizard({
			adminEmail: ADMIN_EMAIL,
			adminPassword: password,
			providerKey: providerKey || undefined
		})
		if (res.ok) onDone()
		else {
			status.style.color = '#c00'
			status.textContent = res.error ?? 'Setup failed.'
			goBtn.disabled = false
		}
	})
}
