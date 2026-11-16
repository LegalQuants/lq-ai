<script lang="ts">
  import { auth } from '$lib/lq-ai/auth/store';
  import LqText from './shared/LqText.svelte';
  import LqTitle from './shared/LqTitle.svelte';

  $: user = $auth.user;
  $: displayName = user?.display_name || user?.email || 'there';

  const now = new Date();
  const dayOfWeek = now.toLocaleDateString('en-US', { weekday: 'long' });
  const dateString = now.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
</script>

<header style="margin-bottom: var(--lq-space-6);">
  <LqTitle order={1} size="26" weight="semibold" tone="primary">Welcome back, {displayName}</LqTitle>
  <LqText as="p" size="12" tone="tertiary">{dayOfWeek}, {dateString}</LqText>
</header>
