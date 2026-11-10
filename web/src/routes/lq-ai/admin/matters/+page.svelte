<script lang="ts">
	import { onMount } from 'svelte';
	import { matterAdministration as api } from '$lib/lq-ai/api/matterAdministration';
	import type {
		ManagedMatter,
		MatterMember,
		MatterRole,
		DirectoryPerson,
		ShareScope
	} from '$lib/lq-ai/api/matterAdministration';

	let matters: ManagedMatter[] = [];
	let people: DirectoryPerson[] = [];
	let members: MatterMember[] = [];
	let selected: ManagedMatter | null = null;
	let roles: Record<string, MatterRole> = {};
	let reason = '';
	let addUser = '';
	let addRole: MatterRole = 'reader';
	let newOwner = '';
	let formerRole: MatterRole = 'reader';
	let scope: ShareScope = 'personal';
	let busy = false;
	let error = '';
	let notice = '';
	let offset = 0;
	const roleOptions: MatterRole[] = ['lead', 'contributor', 'reader', 'blocked'];
	const roleLabel = (role: MatterRole) =>
		role === 'blocked' ? 'Screened' : role.charAt(0).toUpperCase() + role.slice(1);
	onMount(() => load());

	async function load() {
		busy = true;
		error = '';
		try {
			[matters, people] = await Promise.all([api.list(offset), api.directory()]);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
	async function choose(matter: ManagedMatter) {
		busy = true;
		error = '';
		notice = '';
		selected = null;
		reason = '';
		try {
			members = await api.members(matter.id);
			roles = Object.fromEntries(members.map((m) => [m.user_id, m.role]));
			selected = matter;
			scope = matter.share_scope;
			newOwner = '';
			addUser = '';
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
	async function action(run: () => Promise<unknown>, message: string) {
		if (!selected || !reason.trim() || busy) return;
		const matterId = selected.id;
		busy = true;
		error = '';
		notice = '';
		let saved = false;
		try {
			await run();
			saved = true;
			[matters, members] = await Promise.all([api.list(offset), api.members(matterId)]);
			selected = matters.find((m) => m.id === matterId) ?? null;
			roles = Object.fromEntries(members.map((m) => [m.user_id, m.role]));
			if (selected) scope = selected.share_scope;
			reason = '';
			addUser = '';
			newOwner = '';
			notice = message;
		} catch (e) {
			if (saved) {
				selected = null;
				members = [];
				roles = {};
				reason = '';
				notice = 'Change saved. Reload to refresh administrative access.';
			}
			error = e instanceof Error ? e.message : String(e);
		} finally {
			busy = false;
		}
	}
	async function nextPage(delta: number) {
		offset = Math.max(0, offset + delta);
		selected = null;
		await load();
	}
</script>

<svelte:head><title>Matter access administration | LQ.AI</title></svelte:head>
<section class="management">
	<header>
		<h1>Matter access administration</h1>
		<p>
			Manage ownership, membership, and ethical screens. These controls do not grant access to
			matter content.
		</p>
	</header>
	{#if error}<p class="error" role="alert">{error}</p>{/if}
	{#if notice}<p class="notice" role="status">{notice}</p>{/if}
	<div class="columns">
		<section class="matter-list" aria-label="Matters">
			<h2>Matters</h2>
			{#if busy && matters.length === 0}<p role="status">Loading matters…</p>{/if}
			{#each matters as matter (matter.id)}
				<button
					class="matter"
					class:chosen={selected?.id === matter.id}
					disabled={busy}
					on:click={() => choose(matter)}
				>
					<strong>{matter.name}</strong><span
						>{matter.archived_at ? 'Archived' : 'Active'} · {matter.share_scope === 'org'
							? 'Organisation may read'
							: 'Explicit members only'}</span
					>
				</button>
			{/each}
			{#if !busy && matters.length === 0}<p>No matters are available for you to administer.</p>{/if}
			<div class="pagination">
				<button disabled={busy || offset === 0} on:click={() => nextPage(-100)}>Previous</button
				><button disabled={busy || matters.length < 100} on:click={() => nextPage(100)}>Next</button
				>
			</div>
		</section>
		<section class="controls" aria-label="Access controls">
			{#if selected}
				<h2>{selected.name}</h2>
				<label for="intervention-reason">Reason for this change</label>
				<textarea
					id="intervention-reason"
					bind:value={reason}
					maxlength="1000"
					disabled={busy}
					placeholder="Explain the administrative intervention"
				></textarea>
				<p class="hint">
					A reason is required and recorded with every change. Screened administrators cannot remove
					their own restrictions.
				</p>
				<h3>People on this matter</h3>
				{#each members as member (member.user_id)}
					<div class="member">
						<div>
							<strong>{member.display_name || member.email}</strong><span
								>{member.email}{member.is_owner ? ' · Owner' : ''}</span
							>
						</div>
						{#if member.is_owner}<span>Lead</span>{:else}
							<label class="sr-only" for={'role-' + member.user_id}>Role for {member.email}</label>
							<select
								id={'role-' + member.user_id}
								bind:value={roles[member.user_id]}
								disabled={busy}
							>
								{#each roleOptions as role}<option value={role}>{roleLabel(role)}</option>{/each}
							</select>
							<button
								disabled={busy || !reason.trim()}
								on:click={() =>
									action(
										() => api.change(selected!.id, member.user_id, roles[member.user_id], reason),
										'Role updated.'
									)}>Save role</button
							>
							<button
								disabled={busy || !reason.trim()}
								on:click={() => {
									if (
										confirm(
											member.role === 'blocked'
												? 'Lift this screen? Organisation-wide sharing may restore access.'
												: 'Remove this person from the roster?'
										)
									)
										action(
											() => api.remove(selected!.id, member.user_id, reason),
											member.role === 'blocked' ? 'Screen lifted.' : 'Roster entry removed.'
										);
								}}>{member.role === 'blocked' ? 'Lift screen' : 'Remove'}</button
							>
						{/if}
					</div>
				{/each}
				<h3>Add a person or impose a screen</h3>
				<label for="add-person">Person</label><select
					id="add-person"
					bind:value={addUser}
					disabled={busy}
					><option value="">Choose a person</option
					>{#each people.filter((p) => !members.some((m) => m.user_id === p.id)) as person}<option
							value={person.id}>{person.display_name || person.email} ({person.email})</option
						>{/each}</select
				>
				<label for="add-role">Role</label><select id="add-role" bind:value={addRole} disabled={busy}
					>{#each roleOptions as role}<option value={role}>{roleLabel(role)}</option>{/each}</select
				>
				<button
					disabled={busy || !reason.trim() || !addUser}
					on:click={() =>
						action(
							() => api.add(selected!.id, addUser, addRole, reason),
							addRole === 'blocked' ? 'Screen imposed.' : 'Person added.'
						)}>{addRole === 'blocked' ? 'Impose screen' : 'Add person'}</button
				>
				<h3>Sharing</h3>
				<label for="share-scope">Who may read</label><select
					id="share-scope"
					bind:value={scope}
					disabled={busy}
					><option value="personal">Owner and explicit members</option><option value="members"
						>Explicitly restricted to members</option
					><option value="org">Organisation, except screened people</option></select
				>
				<button
					disabled={busy || !reason.trim() || scope === selected.share_scope}
					on:click={() =>
						action(() => api.policy(selected!.id, scope, reason), 'Sharing policy updated.')}
					>Save sharing policy</button
				>
				<h3>Transfer ownership</h3>
				<p class="hint">
					Transfers this matter and the current owner's chats, files, and knowledge bases held in
					it. Historical message authorship stays intact. Running autonomous work must be halted
					first.
				</p>
				<label for="new-owner">New owner</label><select
					id="new-owner"
					bind:value={newOwner}
					disabled={busy}
					><option value="">Choose a new owner</option
					>{#each people.filter((p) => p.id !== selected?.owner_id) as person}<option
							value={person.id}>{person.display_name || person.email} ({person.email})</option
						>{/each}</select
				>
				<label for="former-owner-role">Former owner's access</label><select
					id="former-owner-role"
					bind:value={formerRole}
					disabled={busy}
					>{#each roleOptions as role}<option value={role}>{roleLabel(role)}</option>{/each}</select
				>
				<button
					disabled={busy || !reason.trim() || !newOwner}
					on:click={() => {
						if (
							confirm(
								'Transfer ownership and custody of the matter’s work? This change is recorded in the audit log.'
							)
						)
							action(
								() => api.transfer(selected!.id, newOwner, formerRole, reason),
								'Ownership transferred.'
							);
					}}>Transfer ownership</button
				>
			{:else}<p>Select a matter to manage its access.</p>{/if}
		</section>
	</div>
</section>

<style>
	.management {
		padding: var(--lq-space-6);
		color: var(--lq-text);
	}
	header {
		max-width: 70ch;
		margin-bottom: var(--lq-space-5);
	}
	h1 {
		font-size: 1.6rem;
		font-weight: 650;
	}
	h2 {
		font-size: 1.2rem;
		font-weight: 600;
	}
	h3 {
		font-size: 1rem;
		font-weight: 600;
		margin-top: 1.6rem;
	}
	p {
		line-height: 1.6;
	}
	.hint,
	span {
		color: var(--lq-text-secondary);
		font-size: 0.9rem;
	}
	.columns {
		display: grid;
		grid-template-columns: minmax(220px, 1fr) minmax(360px, 2fr);
		gap: 2rem;
	}
	.matter-list,
	.controls {
		min-width: 0;
	}
	.matter {
		display: block;
		width: 100%;
		text-align: left;
		margin: 0.5rem 0;
	}
	.matter span,
	.member span {
		display: block;
	}
	.chosen {
		border-color: var(--lq-accent);
	}
	.member {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		border-bottom: 1px solid var(--lq-border);
		padding: 0.8rem 0;
	}
	.member > div {
		flex: 1;
		min-width: 180px;
	}
	label {
		display: block;
		margin-top: 0.7rem;
	}
	select,
	textarea {
		padding: 0.55rem;
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		background: var(--lq-surface);
		color: var(--lq-text);
		max-width: 100%;
	}
	textarea {
		display: block;
		width: 100%;
		min-height: 80px;
	}
	button {
		padding: 0.55rem 0.75rem;
		background: var(--lq-surface);
		border: 1px solid var(--lq-border);
		border-radius: 6px;
		color: var(--lq-text);
	}
	button:disabled {
		opacity: 0.5;
	}
	button:focus-visible,
	select:focus-visible,
	textarea:focus-visible {
		outline: 2px solid var(--lq-accent);
		outline-offset: 2px;
	}
	.error {
		color: var(--lq-danger, #b42318);
	}
	.notice {
		color: var(--lq-text);
	}
	.pagination {
		display: flex;
		gap: 0.5rem;
		margin-top: 1rem;
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
	}
	@media (max-width: 760px) {
		.columns {
			grid-template-columns: 1fr;
		}
		.management {
			padding: 1rem;
		}
	}
</style>
