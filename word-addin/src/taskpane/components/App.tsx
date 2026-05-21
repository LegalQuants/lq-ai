/**
 * Root component for the LQ.AI Word add-in task pane.
 *
 * M3-B1 + M3-B2 scope: header + tab strip + a deep-link card per tab,
 * gated behind LQ.AI sign-in (per Decision B-3, OAuth via Office.js
 * Dialog API + the deployment's existing JWT issuer).
 *
 * The feature surfaces inside each tab (chat against the open document
 * for Chat, skill execution with tracked changes for Skills, playbook
 * execution for Playbooks, plus the Inference Tier badge in the header)
 * are descoped to M4 / community contribution per [DE-287]. Decision
 * B-4 in the Phase B prep doc locks the placeholder treatment: each
 * tab renders a "coming soon" card with a button that opens the
 * equivalent web-app surface in a new browser tab — giving the
 * operator a usable add-in at v0.3.0 while making the
 * community-contribution surface explicit.
 */
import React, { useState } from "react";
import { Header } from "./Header";
import { TabStrip, type TabId } from "./TabStrip";
import { DeepLinkCard } from "./DeepLinkCard";
import { SignInGate } from "./SignInGate";
import { getSession, logout, type AuthSession } from "../auth";

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

  if (!session) {
    return (
      <div className="lq-app lq-app-signin">
        <Header deploymentOrigin={window.location.origin} user={null} />
        <main className="lq-content">
          <SignInGate onSignedIn={setSession} />
        </main>
      </div>
    );
  }

  async function handleSignOut(): Promise<void> {
    await logout();
    setSession(null);
  }

  const content = TAB_CONTENT[activeTab];
  const deploymentOrigin = window.location.origin;
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
