<script lang="ts">
  const repoUrl = 'https://github.com/LegalQuants/lq-ai';
  const spec10Url = `${repoUrl}/blob/main/docs/PRD.md#10-open-source-and-forkability`;
  const adr0009Url = `${repoUrl}/blob/main/docs/adr/0009-shell-coexistence-boundary.md`;
</script>

<div class="fork-callout">
  <h2 class="fork-title">Build your own frontend</h2>
  <p class="fork-desc">
    LQ.AI's frontend is open-source under Apache-2.0. The API is contract-stable per OpenAPI —
    you can replace this shell entirely and the backend keeps working.
  </p>

  <div class="fork-links">
    <a href={repoUrl} target="_blank" rel="noopener noreferrer" class="fork-link">GitHub repo</a>
    <a href={spec10Url} target="_blank" rel="noopener noreferrer" class="fork-link">Spec §10 — Forkability commitment</a>
    <a href={adr0009Url} target="_blank" rel="noopener noreferrer" class="fork-link">ADR 0009 — Shell coexistence boundary</a>
  </div>

  <div class="fork-steps">
    <p class="fork-steps-label">How to fork</p>
    <ol class="fork-steps-list">
      <li>Clone the repo and duplicate <code>web/</code> into your own project.</li>
      <li>Swap CSS variables in <code>web/src/lib/lq-ai/styles/practice.css</code> to apply your brand.</li>
      <li>Point <code>PUBLIC_LQ_AI_API_BASE_URL</code> at your backend deployment.</li>
      <li>Redeploy via the provided Helm chart or your own container setup.</li>
    </ol>
  </div>
</div>

<style>
  .fork-callout {
    background: var(--lq-surface);
    border: 2px solid var(--lq-accent);
    border-radius: var(--lq-radius);
    padding: var(--lq-space-5);
  }

  .fork-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--lq-text);
    margin: 0 0 var(--lq-space-3);
  }

  .fork-desc {
    font-size: 14px;
    color: var(--lq-text-secondary);
    margin: 0 0 var(--lq-space-4);
    line-height: 1.5;
  }

  .fork-links {
    display: flex;
    flex-wrap: wrap;
    gap: var(--lq-space-3);
    margin-bottom: var(--lq-space-4);
  }

  .fork-link {
    color: var(--lq-accent);
    text-decoration: none;
    font-size: 14px;
    font-weight: 500;
  }

  .fork-link:hover {
    text-decoration: underline;
  }

  .fork-steps {
    border-top: 1px solid var(--lq-border);
    padding-top: var(--lq-space-4);
  }

  .fork-steps-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--lq-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0 0 var(--lq-space-2);
  }

  .fork-steps-list {
    margin: 0;
    padding-left: var(--lq-space-5);
    display: flex;
    flex-direction: column;
    gap: var(--lq-space-2);
  }

  .fork-steps-list li {
    font-size: 13px;
    color: var(--lq-text-secondary);
    line-height: 1.5;
  }

  .fork-steps-list code {
    font-family: var(--lq-font-mono);
    font-size: 12px;
    background: var(--lq-inset);
    border: 1px solid var(--lq-border);
    border-radius: 3px;
    padding: 1px 5px;
    color: var(--lq-text);
  }
</style>
