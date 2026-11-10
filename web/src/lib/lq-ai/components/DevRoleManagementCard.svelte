<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import { beforeNavigate, goto } from '$app/navigation';
	import { listUsers, patchUserRole, createUser, resetUserPassword } from '../api/admin';
	import { LQAIApiError } from '../api/client';
	import { clearSession, getCurrentUser } from '../auth/store';
	import type {
		AdminUserRow,
		AdminUserListQuery,
		UserRole,
		AdminUserCreateRequest
	} from '../types';

	let users: AdminUserRow[] = [];
	let totalCount = 0;
	let limit = 50;
	let offset = 0;

	let loading = true;
	let fetchError = '';

	let roleFilter: UserRole | '' = '';
	let emailQuery = '';

	let inlineError = '';
	let showCreate = false;
	let createEmail = '';
	let displayName = '';
	let createRole: NonNullable<AdminUserCreateRequest['role']> = 'member';
	let resetTarget: AdminUserRow | null = null;
	let submitting = false;
	let actionError = '';
	let temporaryPassword: { email: string; password: string; selfReset: boolean } | null = null;
	let copyStatus = '';
	let emailInput: HTMLInputElement | undefined;
	let confirmationButton: HTMLButtonElement | undefined;
	let passwordInput: HTMLInputElement | undefined;
	let createButton: HTMLButtonElement | undefined;
	let returnFocus: HTMLElement | null = null;
	let disposed = false;

	function clearTemporaryPassword() {
		const selfReset = temporaryPassword?.selfReset;
		temporaryPassword = null;
		copyStatus = '';
		if (selfReset) clearSession();
	}

	function closeAction() {
		showCreate = false;
		resetTarget = null;
		createEmail = '';
		displayName = '';
		createRole = 'member';
		actionError = '';
		(returnFocus?.isConnected ? returnFocus : createButton)?.focus();
	}

	async function openCreate() {
		clearTemporaryPassword();
		closeAction();
		returnFocus = createButton ?? null;
		showCreate = true;
		await tick();
		emailInput?.focus();
	}

	async function openReset(user: AdminUserRow, event: MouseEvent) {
		clearTemporaryPassword();
		closeAction();
		returnFocus = event.currentTarget as HTMLElement;
		resetTarget = user;
		await tick();
		confirmationButton?.focus();
	}

	async function finishAction() {
		const selfReset = temporaryPassword?.selfReset;
		clearTemporaryPassword();
		if (selfReset) {
			await goto('/lq-ai/login');
		} else {
			(returnFocus?.isConnected ? returnFocus : createButton)?.focus();
		}
	}

	async function handleCreate() {
		if (submitting) return;
		submitting = true;
		actionError = '';
		try {
			const created = await createUser({
				email: createEmail.trim(),
				display_name: displayName.trim() || null,
				role: createRole
			});
			if (disposed) return;
			closeAction();
			temporaryPassword = {
				email: created.email,
				password: created.initial_password,
				selfReset: false
			};
			offset = 0;
			await fetchUsers();
			await tick();
			passwordInput?.focus();
		} catch (err) {
			actionError = err instanceof Error ? err.message : 'Could not create user.';
		} finally {
			submitting = false;
		}
	}

	async function handleReset() {
		if (!resetTarget || submitting) return;
		submitting = true;
		actionError = '';
		const selfReset = resetTarget.id === getCurrentUser()?.id;
		try {
			const reset = await resetUserPassword(resetTarget.id);
			if (disposed) return;
			closeAction();
			temporaryPassword = { email: reset.email, password: reset.initial_password, selfReset };
			// A self-reset invalidates this session. Keep the password visible
			// until dismissal; another authenticated request would hide it on 401.
			if (!selfReset) await fetchUsers();
			await tick();
			passwordInput?.focus();
		} catch (err) {
			actionError = err instanceof Error ? err.message : 'Could not reset password.';
		} finally {
			submitting = false;
		}
	}

	async function copyPassword() {
		if (!temporaryPassword) return;
		try {
			await navigator.clipboard.writeText(temporaryPassword.password);
			copyStatus = 'Copied';
		} catch {
			copyStatus = 'Copy failed. Select the password and copy it manually.';
		}
	}

	beforeNavigate(clearTemporaryPassword);
	onDestroy(() => {
		disposed = true;
		clearTemporaryPassword();
	});

	function formatRelativeDate(isoDate: string | null | undefined): string {
		if (!isoDate) return 'never';
		const d = new Date(isoDate);
		const diffMs = Date.now() - d.getTime();
		const diffDays = Math.floor(diffMs / 86400000);
		if (diffDays === 0) return 'today';
		if (diffDays === 1) return 'yesterday';
		if (diffDays < 30) return `${diffDays}d ago`;
		const diffMonths = Math.floor(diffDays / 30);
		if (diffMonths < 12) return `${diffMonths}mo ago`;
		return `${Math.floor(diffMonths / 12)}y ago`;
	}

	async function fetchUsers() {
		loading = true;
		fetchError = '';
		try {
			const query: AdminUserListQuery = { limit, offset };
			if (roleFilter) query.role = roleFilter;
			if (emailQuery.trim()) query.email_q = emailQuery.trim();
			const resp = await listUsers(query);
			users = resp.users;
			totalCount = resp.total_count;
		} catch (err) {
			fetchError = err instanceof Error ? err.message : 'Failed to load users.';
		} finally {
			loading = false;
		}
	}

	async function handleRoleChange(userId: string, newRole: UserRole) {
		inlineError = '';
		try {
			const updated = await patchUserRole(userId, newRole);
			users = users.map((u) => (u.id === userId ? { ...u, role: updated.role } : u));
		} catch (err) {
			if (err instanceof LQAIApiError && err.status === 409) {
				inlineError = "Can't demote the last admin. Promote another user first.";
			} else {
				inlineError = err instanceof Error ? err.message : 'Failed to update role.';
			}
		}
	}

	function prevPage() {
		if (offset > 0) {
			offset = Math.max(0, offset - limit);
			fetchUsers();
		}
	}

	function nextPage() {
		if (offset + limit < totalCount) {
			offset += limit;
			fetchUsers();
		}
	}

	function applyFilters() {
		offset = 0;
		fetchUsers();
	}

	onMount(fetchUsers);
</script>

<div class="dev-card">
	<div class="card-heading">
		<h2 class="dev-card-title">Role management</h2>
		<button
			type="button"
			class="page-btn"
			bind:this={createButton}
			on:click={openCreate}
			disabled={submitting || !!temporaryPassword || showCreate}>Create user</button
		>
	</div>

	{#if showCreate}
		<form
			class="action-panel"
			aria-labelledby="create-user-title"
			on:submit|preventDefault={handleCreate}
		>
			<h3 id="create-user-title">Create user</h3>
			<label for="create-user-email">Email</label>
			<input
				id="create-user-email"
				class="filter-input"
				type="email"
				bind:this={emailInput}
				bind:value={createEmail}
				required
				autocomplete="off"
				disabled={submitting}
			/>
			<label for="create-user-name">Display name (optional)</label>
			<input
				id="create-user-name"
				class="filter-input"
				type="text"
				bind:value={displayName}
				maxlength="200"
				autocomplete="off"
				disabled={submitting}
			/>
			<label for="create-user-role">Role</label>
			<select
				id="create-user-role"
				class="filter-select"
				bind:value={createRole}
				disabled={submitting}
			>
				<option value="member">Member</option>
				<option value="viewer">Viewer</option>
				<option value="admin">Admin</option>
			</select>
			{#if actionError}<p class="inline-error" role="alert">{actionError}</p>{/if}
			<div class="action-buttons">
				<button class="page-btn" type="submit" disabled={submitting}
					>{submitting ? 'Creating…' : 'Create user'}</button
				>
				<button class="page-btn" type="button" on:click={closeAction} disabled={submitting}
					>Cancel</button
				>
			</div>
		</form>
	{/if}

	{#if resetTarget}
		<section class="action-panel" aria-labelledby="reset-password-title">
			<h3 id="reset-password-title">Reset password for {resetTarget.email}?</h3>
			<p>
				This replaces their password and signs them out. They must change the temporary password at
				their next sign-in. MFA stays enabled if already set up.
			</p>
			{#if resetTarget.id === getCurrentUser()?.id}
				<p>
					You are resetting your own password. Save the temporary password before signing in again.
				</p>
			{/if}
			{#if actionError}<p class="inline-error" role="alert">{actionError}</p>{/if}
			<div class="action-buttons">
				<button
					class="page-btn"
					type="button"
					bind:this={confirmationButton}
					on:click={handleReset}
					disabled={submitting}>{submitting ? 'Resetting…' : 'Confirm reset'}</button
				>
				<button class="page-btn" type="button" on:click={closeAction} disabled={submitting}
					>Cancel</button
				>
			</div>
		</section>
	{/if}

	{#if temporaryPassword}
		<section class="action-panel" aria-labelledby="temporary-password-title">
			<h3 id="temporary-password-title">Temporary password for {temporaryPassword.email}</h3>
			<p>
				Save it now and share it securely. It disappears when you dismiss this panel. The user must
				change it at sign-in.
			</p>
			<label for="temporary-password">Temporary password</label>
			<input
				id="temporary-password"
				class="filter-input password-display"
				bind:this={passwordInput}
				type="text"
				value={temporaryPassword.password}
				readonly
				autocomplete="off"
				spellcheck="false"
			/>
			<div class="action-buttons">
				<button class="page-btn" type="button" on:click={copyPassword}>Copy password</button>
				<button class="page-btn" type="button" on:click={finishAction}
					>{temporaryPassword.selfReset ? 'Continue to sign in' : 'Done'}</button
				>
			</div>
			<p class="state-msg" role="status">{copyStatus}</p>
		</section>
	{/if}

	<div class="filters">
		<select
			class="filter-select"
			bind:value={roleFilter}
			on:change={applyFilters}
			aria-label="Filter by role"
			disabled={submitting || !!temporaryPassword}
		>
			<option value="">All roles</option>
			<option value="admin">admin</option>
			<option value="member">member</option>
			<option value="viewer">viewer</option>
		</select>
		<input
			type="text"
			class="filter-input"
			placeholder="Search email..."
			bind:value={emailQuery}
			on:input={applyFilters}
			aria-label="Filter by email"
			disabled={submitting || !!temporaryPassword}
		/>
	</div>

	{#if inlineError}
		<div class="inline-error" role="alert">{inlineError}</div>
	{/if}

	{#if loading}
		<p class="state-msg">Loading users…</p>
	{:else if fetchError}
		<p class="state-msg state-msg--error">{fetchError}</p>
	{:else if users.length === 0}
		<p class="state-msg">No users found.</p>
	{:else}
		<div class="table-wrap">
			<table class="users-table">
				<thead>
					<tr>
						<th>Email</th>
						<th>Role</th>
						<th>Last login</th>
						<th>Deletion</th>
						<th>Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each users as user (user.id)}
						<tr>
							<td class="email-cell" title={user.email}>{user.email}</td>
							<td>
								<select
									class="role-select"
									value={user.role}
									disabled={submitting || !!temporaryPassword}
									on:change={(e) =>
										handleRoleChange(user.id, (e.target as HTMLSelectElement).value as UserRole)}
									aria-label={`Role for ${user.email}`}
								>
									<option value="admin">admin</option>
									<option value="member">member</option>
									<option value="viewer">viewer</option>
								</select>
							</td>
							<td class="secondary-cell">{formatRelativeDate(user.last_login_at)}</td>
							<td>
								{#if user.deletion_scheduled_at}
									<span class="deletion-pill">Scheduled</span>
								{/if}
							</td>
							<td>
								<button
									class="page-btn"
									type="button"
									on:click={(event) => openReset(user, event)}
									disabled={submitting || !!temporaryPassword}
									aria-label={`Reset password for ${user.email}`}
								>
									Reset password
								</button>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div class="pagination">
			<span class="pagination-info"
				>Showing {offset + 1}–{Math.min(offset + limit, totalCount)} of {totalCount}</span
			>
			<div class="pagination-btns">
				<button
					class="page-btn"
					on:click={prevPage}
					disabled={offset === 0 || submitting || !!temporaryPassword}>Prev</button
				>
				<button
					class="page-btn"
					on:click={nextPage}
					disabled={offset + limit >= totalCount || submitting || !!temporaryPassword}>Next</button
				>
			</div>
		</div>
	{/if}
</div>

<style>
	.card-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--lq-space-3);
		margin-bottom: var(--lq-space-4);
	}
	.card-heading .dev-card-title {
		margin: 0;
	}
	.action-panel {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-2);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		background: var(--lq-inset);
		padding: var(--lq-space-3);
		margin-bottom: var(--lq-space-4);
		font-size: 13px;
	}
	.action-panel h3 {
		font-size: 14px;
		font-weight: 600;
		margin: 0;
		overflow-wrap: anywhere;
	}
	.action-panel p {
		margin: 0 0 var(--lq-space-2);
	}
	.action-panel label {
		font-weight: 500;
	}
	.action-panel .filter-input {
		width: 100%;
		min-width: 0;
	}
	.action-buttons {
		display: flex;
		flex-wrap: wrap;
		gap: var(--lq-space-2);
		margin-top: var(--lq-space-2);
	}
	.password-display {
		font-family: var(--lq-font-mono, monospace);
	}
	button:focus-visible,
	input:focus-visible,
	select:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.dev-card {
		min-width: 0;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius);
		padding: var(--lq-space-5);
	}

	.dev-card-title {
		font-size: 15px;
		font-weight: 600;
		color: var(--lq-text);
		margin: 0 0 var(--lq-space-4);
	}

	.filters {
		display: flex;
		gap: var(--lq-space-3);
		margin-bottom: var(--lq-space-4);
		flex-wrap: wrap;
	}

	.filter-select,
	.filter-input {
		padding: var(--lq-space-2) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		background: var(--lq-surface);
		color: var(--lq-text);
		font-size: 13px;
	}

	.filter-input {
		flex: 1;
		min-width: 160px;
	}

	.inline-error {
		background: var(--lq-error-soft);
		border: 1px solid var(--lq-error-border);
		color: var(--lq-error);
		border-radius: var(--lq-radius-sm);
		padding: var(--lq-space-2) var(--lq-space-3);
		font-size: 13px;
		margin-bottom: var(--lq-space-3);
	}

	.state-msg {
		font-size: 14px;
		color: var(--lq-text-secondary);
		margin: 0;
	}

	.state-msg--error {
		color: var(--lq-error);
	}

	.table-wrap {
		overflow-x: auto;
		margin-bottom: var(--lq-space-4);
	}

	.users-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}

	.users-table .page-btn {
		white-space: nowrap;
	}

	.users-table th {
		text-align: left;
		font-weight: 600;
		color: var(--lq-text-secondary);
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
		white-space: nowrap;
	}

	.users-table td {
		padding: var(--lq-space-2) var(--lq-space-3);
		border-bottom: 1px solid var(--lq-border);
		vertical-align: middle;
	}

	.email-cell {
		max-width: 200px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.secondary-cell {
		color: var(--lq-text-secondary);
	}

	.role-select {
		padding: 2px var(--lq-space-2);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		background: var(--lq-surface);
		color: var(--lq-text);
		font-size: 13px;
		cursor: pointer;
	}

	.deletion-pill {
		display: inline-block;
		padding: 2px 8px;
		background: var(--lq-warn-soft);
		color: var(--lq-warn);
		border: 1px solid var(--lq-warn-border);
		border-radius: var(--lq-radius-pill);
		font-size: 11px;
		font-weight: 500;
	}

	.pagination {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: var(--lq-space-2);
	}

	.pagination-info {
		font-size: 12px;
		color: var(--lq-text-secondary);
	}

	.pagination-btns {
		display: flex;
		gap: var(--lq-space-2);
	}

	.page-btn {
		padding: var(--lq-space-1) var(--lq-space-3);
		border: 1px solid var(--lq-border);
		border-radius: var(--lq-radius-sm);
		background: var(--lq-surface);
		color: var(--lq-text);
		font-size: 13px;
		cursor: pointer;
		transition: background 0.12s;
	}

	.page-btn:hover:not(:disabled) {
		background: var(--lq-inset);
	}

	.page-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
</style>
