/**
 * Task pane header.
 *
 * Renders the deployment's display name (derived from the deployment origin
 * — the manifest's templated `DEPLOYMENT_DISPLAY_NAME` lives in the manifest
 * and is not currently exposed to the task pane; deriving from origin is
 * sufficient for v0.3.0) and an Inference Tier badge placeholder.
 *
 * The badge is intentionally inert at M3-B1. The tier-badge implementation
 * lands with M3-B6 / DE-287 (community contribution) and will source tier
 * state from the `/api/v1/inference-tier-detail` endpoint per [PRD §3.13].
 */
import React from "react";

type HeaderProps = {
  deploymentOrigin: string;
};

export const Header: React.FC<HeaderProps> = ({ deploymentOrigin }) => {
  // For M3-B1, we show the origin host as a recognizable label. The
  // deployment's branded display name lands when M3-B2 OAuth exchanges
  // a token that carries the deployment metadata.
  const originHost = (() => {
    try {
      return new URL(deploymentOrigin).host;
    } catch {
      return "LQ.AI";
    }
  })();

  return (
    <header className="lq-header" role="banner">
      <div className="lq-header-brand">
        <span className="lq-header-logo" aria-hidden="true">
          LQ
        </span>
        <span className="lq-header-name" title={deploymentOrigin}>
          {originHost}
        </span>
      </div>
      <div
        className="lq-header-tier-badge lq-header-tier-badge-placeholder"
        title="Inference Tier badge — surface lands with DE-287 (community contribution / M4)"
        aria-label="Inference Tier indicator (placeholder; not yet wired)"
      >
        Tier —
      </div>
    </header>
  );
};
