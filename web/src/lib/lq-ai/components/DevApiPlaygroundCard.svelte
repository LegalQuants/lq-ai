<script lang="ts">
  import { getAccessToken } from '../auth/store';

  let copied = false;
  let copyError = false;

  $: token = getAccessToken();
  $: truncated = token ? token.slice(0, 12) + '...' : '(no active session)';

  async function copyToken() {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token);
      copied = true;
      copyError = false;
      setTimeout(() => { copied = false; }, 2000);
    } catch {
      copyError = true;
      setTimeout(() => { copyError = false; }, 2000);
    }
  }
</script>

<div class="dev-card">
  <h2 class="dev-card-title">API playground</h2>
  <p class="playground-desc">
    Copy your current JWT into Swagger UI's Authorize dialog to make authenticated requests.
  </p>
  <div class="token-row">
    <code
      class="token-display"
      aria-label="JWT token (copy to clipboard)"
    >{truncated}</code>
    <button
      type="button"
      class="copy-btn"
      on:click={copyToken}
      disabled={!token}
    >
      {#if copied}
        Copied
      {:else if copyError}
        Failed
      {:else}
        Copy
      {/if}
    </button>
  </div>
  <p class="playground-footer">
    Paste into Swagger UI's Authorize dialog (Bearer + the token). Token expires; copy again later if a request 401s.
  </p>
</div>

<style>
  .dev-card {
    background: var(--lq-surface);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-5);
  }

  .dev-card-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--lq-text);
    margin: 0 0 var(--lq-space-3);
  }

  .playground-desc {
    font-size: 14px;
    color: var(--lq-text-secondary);
    margin: 0 0 var(--lq-space-4);
  }

  .token-row {
    display: flex;
    align-items: center;
    gap: var(--lq-space-3);
    margin-bottom: var(--lq-space-3);
  }

  .token-display {
    flex: 1;
    font-family: var(--lq-font-mono);
    font-size: 13px;
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-sm);
    padding: var(--lq-space-2) var(--lq-space-3);
    color: var(--lq-text);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .copy-btn {
    flex-shrink: 0;
    padding: var(--lq-space-2) var(--lq-space-4);
    border: 1px solid var(--lq-border);
    border-radius: var(--lq-radius-sm);
    background: var(--lq-surface);
    color: var(--lq-text);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.12s, color 0.12s;
  }

  .copy-btn:hover:not(:disabled) {
    background: var(--lq-inset);
  }

  .copy-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .playground-footer {
    font-size: 12px;
    color: var(--lq-text-secondary);
    margin: 0;
  }
</style>
