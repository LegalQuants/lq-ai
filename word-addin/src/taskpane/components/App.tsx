/**
 * Root component for the LQ.AI Word add-in task pane.
 *
 * Renders three exclusive states:
 *
 *   1. "Update needed" overlay — installed add-in version falls outside
 *      the deployment's compatibility range (M3-B8 version handshake).
 *      Blocks every other UI path so an out-of-date add-in can't push
 *      the operator through a broken OAuth handshake.
 *   2. Sign-in gate — version is compatible (or check is "unknown") but
 *      no LQ.AI session is stored locally (M3-B2 OAuth).
 *   3. Authenticated layout — header + tab strip + deep-link card per
 *      tab. The feature surfaces inside each tab are descoped to M4 /
 *      community contribution per PRD §9 DE-287.
 */
import React, { useEffect, useState } from "react";
import { Header } from "./Header";
import { TabStrip, type TabId } from "./TabStrip";
import { DeepLinkCard } from "./DeepLinkCard";
import { SignInGate } from "./SignInGate";
import { UpdateNeededOverlay } from "./UpdateNeededOverlay";
import { getSession, logout, type AuthSession } from "../auth";
import { fetchVersionInfo, type VersionInfo } from "../version";

type TabContent = {
  title: string;
  body: string;
  webAppPath: string;
};

const TAB_CONTENT: Record<TabId, TabContent> = {
  chat: {
    title: "Chat with the open document",
    body: "In-Word chat against the open document is on the M4 / community-contribution roadmap (DE-287). Until then, you can chat against the same documents in the LQ.AI web app — open it in a new browser tab and your document context follows.",
    webAppPath: "/lq-ai",
  },
  skills: {
    title: "Run a skill in Word",
    body: "Running LQ.AI skills against the open document with redlines as tracked changes and assessments as Word comments lands with M4 / community contribution (DE-287). The same skills run in the LQ.AI web app today — open the skill library in a new tab.",
    webAppPath: "/lq-ai",
  },
  playbooks: {
    title: "Run a playbook in Word",
    body: "Playbook execution in Word — with per-position comments and tracked changes against matched clauses — lands with M4 / community contribution (DE-287). The web app's playbook executor is fully shipped; open it in a new tab to run a playbook against this document.",
    webAppPath: "/lq-ai/playbooks",
  },
};

export const App: React.FC = () => {
  const [session, setSession] = useState<AuthSession | null>(() => getSession());
  const [activeTab, setActiveTab] = useState<TabId>("chat");
  const [version, setVersion] = useState<VersionInfo | null>(null);

  // Run the version handshake once on mount. The check is best-effort:
  // a failed request renders `status="unknown"` and we fall through to
  // the normal sign-in / authenticated layouts so an offline operator
  // isn't blocked from at least seeing the task pane. The overlay only
  // appears for the two strict-incompatibility cases.
  useEffect(() => {
    let cancelled = false;
    void fetchVersionInfo().then((info) => {
      if (!cancelled) setVersion(info);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const deploymentOrigin = window.location.origin;

  // State 1 — Update-needed overlay blocks every other UI path. The
  // overlay's heading and copy differ based on which side of the range
  // is broken; UpdateNeededOverlay handles both cases internally.
  if (
    version !== null &&
    (version.status === "addin_outdated" ||
      version.status === "deployment_outdated")
  ) {
    return (
      <div className="lq-app lq-app-update-needed">
        <Header deploymentOrigin={deploymentOrigin} user={null} />
        <main className="lq-content">
          <UpdateNeededOverlay info={version} />
        </main>
      </div>
    );
  }

  // State 2 — Unauthenticated. Same layout as the sign-in path; the
  // version handshake hasn't blocked it, so the user can proceed.
  if (!session) {
    return (
      <div className="lq-app lq-app-signin">
        <Header deploymentOrigin={deploymentOrigin} user={null} />
        <main className="lq-content">
          {version?.status === "unknown" && (
            <VersionUnknownBanner reason={version.error} />
          )}
          <SignInGate onSignedIn={setSession} />
        </main>
      </div>
    );
  }

  async function handleSignOut(): Promise<void> {
    await logout();
    setSession(null);
  }

  // State 3 — Authenticated tab strip.
  const content = TAB_CONTENT[activeTab];
  const deepLinkHref = `${deploymentOrigin}${content.webAppPath}`;

  return (
    <div className="lq-app">
      <Header
        deploymentOrigin={deploymentOrigin}
        user={session.user}
        onSignOut={handleSignOut}
      />
      <TabStrip activeTab={activeTab} onTabChange={setActiveTab} />
      <main className="lq-content">
        {version?.status === "unknown" && (
          <VersionUnknownBanner reason={version.error} />
        )}
        <DeepLinkCard
          title={content.title}
          body={content.body}
          href={deepLinkHref}
        />
      </main>
      <footer className="lq-footer">
        <a
          href={`${deploymentOrigin}/lq-ai`}
          target="_blank"
          rel="noopener noreferrer"
        >
          Open LQ.AI web app
        </a>
        <span className="lq-footer-sep">·</span>
        <a
          href="https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution"
          target="_blank"
          rel="noopener noreferrer"
        >
          Contribute (DE-287)
        </a>
      </footer>
    </div>
  );
};

/** Soft warning shown when the version handshake failed entirely. The
 *  add-in continues to work so an offline operator isn't blocked, but
 *  the banner tells them we couldn't verify compatibility — useful for
 *  diagnosing "the add-in keeps showing X" support tickets. */
const VersionUnknownBanner: React.FC<{ reason: string | null }> = ({
  reason,
}) => (
  <p className="lq-version-warning" role="status">
    <strong>Version check unavailable.</strong> The add-in couldn&apos;t
    confirm it&apos;s compatible with this deployment
    {reason ? ` (${reason})` : ""}. Sign-in and basic flows still work, but
    let your LQ.AI admin know if you hit something unexpected.
  </p>
);
