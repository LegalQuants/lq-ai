/**
 * Task pane header.
 *
 * Renders the deployment's display name (derived from the deployment origin
 * — the manifest's templated `DEPLOYMENT_DISPLAY_NAME` lives in the manifest
 * and is not currently exposed to the task pane; deriving from origin is
 * sufficient for v0.3.0) and an Inference Tier badge placeholder.
 *
 * When a user is signed in (M3-B2), shows their email + a sign-out button
 * in the header's right-side cluster. The tier badge stays inert at M3-B1
 * / M3-B2 — the badge implementation lands with M3-B6 / DE-287 (community
 * contribution) and will source tier state from the
 * `/api/v1/inference-tier-detail` endpoint per PRD §3.13.
 */
import React from "react";
import type { AuthUser } from "../auth";

type HeaderProps = {
  deploymentOrigin: string;
  user: AuthUser | null;
  onSignOut?: () => void;
};

export const Header: React.FC<HeaderProps> = ({
  deploymentOrigin,
  user,
  onSignOut,
}) => {
  const originHost = (() => {
    try {
      return new URL(deploymentOrigin).host;
    } catch {
      return "LQ.AI";
    }
  })();

  const userLabel = user?.display_name?.trim() || user?.email || null;

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

      <div className="lq-header-right">
        {user && (
          <span className="lq-header-user" title={user.email}>
            {userLabel}
          </span>
        )}
        <div
          className="lq-header-tier-badge lq-header-tier-badge-placeholder"
          title="Inference Tier badge — surface lands with DE-287 (community contribution / M4)"
          aria-label="Inference Tier indicator (placeholder; not yet wired)"
        >
          Tier —
        </div>
        {user && onSignOut && (
          <button
            type="button"
            className="lq-header-signout"
            onClick={onSignOut}
            aria-label="Sign out of LQ.AI"
          >
            Sign out
          </button>
        )}
      </div>
    </header>
  );
};
