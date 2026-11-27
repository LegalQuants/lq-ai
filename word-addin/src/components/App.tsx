/**
 * Root component for the LQ.AI Word add-in task pane.
 *
 * Renders two exclusive states:
 *
 *   1. Sign-in gate — no LQ.AI session is stored locally (M3-B2 OAuth).
 *   2. Authenticated layout — header + tab strip + deep-link card per
 *      tab. The feature surfaces inside each tab are descoped to M4 /
 *      community contribution per PRD §9 DE-287.
 *
 * Version compatibility (M3-B8 handshake) no longer blocks either state.
 * Since the task pane's bundle is always served by (and thus always the
 * same release as) this deployment — never independently installed —
 * the only way the two can actually disagree is a stale cached bundle in
 * Word's WebView. That's surfaced as a dismissible, non-autoclosing
 * notification prompting a refresh, not a blocking overlay: see the
 * `version` effect below.
 */
import React, { useEffect, useState } from "react";
import { fetchVersionInfo } from "@/services/versionClient";
import type { VersionInfo } from "@/domain/version";
import {
  ActionIcon,
  Button,
  Flex,
  Group,
  Menu,
  Tabs,
  Text,
} from "@mantine/core";
import { ChatPanel } from "@/components/ChatPanel";
import Login from "@/auth/Login";
import { useAuth } from "@/auth/AuthContext";
import { actions } from "@/actions";
import { IconLogout, IconMenu2Filled } from "@tabler/icons-react";

import { useDebouncedCallback } from "@mantine/hooks";
import { initializeApp } from "@/services/bootstrap";
import { useAtomValue } from "jotai";
import { skillsAtom, modelsAtom } from "@/store";

type TabContent = {
  title: string;
  webAppPath: string;
  body: React.ReactNode;
  id: string;
};

const tabs: TabContent[] = [
  {
    id: "Chat",
    title: "Chat with the open document",
    webAppPath: "/lq-ai",
    body: <ChatPanel />,
  },
  {
    id: "Skills",
    title: "Run a skill in Word",
    webAppPath: "/lq-ai",
    body: (
      <Flex direction="column">
        Running LQ.AI skills against the open document with redlines as tracked changes and
        assessments as Word comments lands with M4 / community contribution (DE-287). The same
        skills run in the LQ.AI web app today — open the skill library in a new tab.
      </Flex>
    ),
  },
  {
    id: "Playbooks",
    title: "Run a playbook in Word",
    webAppPath: "/lq-ai/playbooks",
    body: (
      <Flex direction="column">
        Playbook execution in Word — with per-position comments and tracked changes against matched
        clauses — lands with M4 / community contribution (DE-287). The web app's playbook executor
        is fully shipped; open it in a new tab to run a playbook against this document.
      </Flex>
    ),
  },
];



let invertedTabList = {
  panel: {
    flex: 1,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
  } as React.CSSProperties,
  list: {
    backgroundColor: "var(--mantine-color-sage-9)",
    borderBottom: "1px solid var(--mantine-color-sage-7)",
    paddingLeft: "var(--mantine-spacing-sm)",
  },
  tab: {
    color: "var(--mantine-color-sage-2)",

    "&:hover": {
      backgroundColor: "var(--mantine-color-sage-8)",
      color: "var(--mantine-color-white)",
    },

    "&[data-active]": {
      color: "var(--mantine-color-white)",
      borderColor: "var(--mantine-color-sage-3)",
    },

    "&[data-active]:hover": {
      backgroundColor: "var(--mantine-color-sage-8)",
    },
  },
  tabLabel: {
    fontWeight: 700,
  },
};

export const App: React.FC = () => {
  const { session, logout } = useAuth();
  const [version, setVersion] = useState<VersionInfo | null>(null);

  // Run the version handshake once on mount. Best-effort: a failed
  // request renders `status="unknown"` and the UI still renders — an
  // offline operator isn't blocked from at least seeing the task pane.
  useEffect(() => {
    let cancelled = false;
    void fetchVersionInfo().then((info) => {
      if (!cancelled) setVersion(info);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Surface non-compatible statuses as a dismissible, non-autoclosing
  // notification instead of blocking the UI — see this file's docstring
  // for why a stale cached bundle (not a genuine version mismatch) is
  // the only realistic cause, and why "refresh" is the fix.
  useEffect(() => {
    if (!version || version.status === "compatible") return;

    if (version.status === "unknown") {
      actions.showNotification(
        "Version check unavailable",
        `The add-in couldn't confirm it's compatible with this deployment${
          version.error ? ` (${version.error})` : ""
        }. Sign-in and basic flows still work, but let your LQ.AI admin know if you hit something unexpected.`,
        false
      );
      return;
    }

    const title =
      version.status === "addin_outdated" ? "Update available" : "Deployment mismatch detected";
    const body =
      version.status === "addin_outdated"
        ? "A newer version of LQ.AI is available. This add-in is served by your deployment, so a refresh usually picks up the latest build."
        : "This add-in reports a newer version than the deployment recognizes. Refresh to reload the latest compatible build.";

    actions.showNotification(
      title,
      <Flex direction="column" gap={6}>
        <Text size="sm">{body}</Text>
        <Button size="xs" color="sage" onClick={() => window.location.reload()}>
          Refresh
        </Button>
      </Flex>,
      false
    );
  }, [version]);

  // Startup data load (skills, models) — explicitly gated on `session`
  // existing, not a module-import-time self-invoke. Firing before login
  // would 401 (no bearer token to attach yet).
  //
  // Also self-heals rather than firing purely off a `session` identity
  // change: the task pane's webview isn't guaranteed to remount for every
  // circumstance that should trigger a (re-)load — React Fast Refresh
  // preserves this component's hook state across an HMR edit, and Word
  // can reuse an already-loaded task pane webview across document
  // switches. In both cases `session` is already truthy and never
  // transitions, so a `[session]`-only effect silently never re-fires and
  // the store stays empty. Checking the atoms themselves means any render
  // with an authenticated session and an empty store retries; `loadingRef`
  // guards against firing a second overlapping fetch while one is still
  // in flight (skills/models resolve independently inside
  // `Promise.all`, so the store can be "still empty" for one tick after
  // the other atom has already been populated).
  const skills = useAtomValue(skillsAtom);
  const models = useAtomValue(modelsAtom);
  const loadingRef = React.useRef(false);

  useEffect(() => {
    if (!session) return;
    if (skills.length > 0 && models.data.length > 0) return;
    if (loadingRef.current) return;

    loadingRef.current = true;
    void initializeApp().finally(() => {
      loadingRef.current = false;
    });
  }, [session, skills, models]);

  // State 1 — Unauthenticated. Version compatibility no longer blocks
  // this — see the notification effect above.
  if (!session) {
    return (
      <div className="lq-app">
        <Login />
      </div>
    );
  }

  return (
    <div className="lq-app">
      <Flex
        component="main"
        direction="column"
        style={{ minHeight: 0, height: "100%", overflow: "hidden" }}
      >
        <Tabs
          defaultValue="Chat"
          style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0}}
          styles={{ panel: invertedTabList.panel }}
        >
          <Tabs.List>
            <Group gap={2}>
              <Menu shadow="md">
                <Menu.Target>
                  <ActionIcon variant="subtle" color="sage">
                    <IconMenu2Filled size={16} />
                  </ActionIcon>
                </Menu.Target>

                <Menu.Dropdown>
                  <Menu.Label>Commands</Menu.Label>
                  <Menu.Item
                    leftSection={<IconLogout size={14} />}
                    onClick={logout}
                    children={"Logout"}
                  />
                </Menu.Dropdown>
              </Menu>

              <Group gap={2}>
                {tabs.map((t, k) => (
                  <Tabs.Tab value={t.id} key={k} children={t.id} />
                ))}
              </Group>
            </Group>
          </Tabs.List>
          {tabs.map((t, k) => (
            <Tabs.Panel value={t.id} key={k} children={t.body} />
          ))}
        </Tabs>
      </Flex>
    </div>
  );
};
