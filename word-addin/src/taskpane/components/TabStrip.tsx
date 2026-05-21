/**
 * Three-tab strip: Chat / Skills / Playbooks.
 *
 * The tabs are visible per the M3-B1 scaffold scope; each tab's content
 * (rendered by the parent) is a deep-link card per Decision B-4 in the
 * Phase B prep doc. The feature surface inside each tab lands with M4 /
 * community contribution per DE-287.
 */
import React from "react";

export type TabId = "chat" | "skills" | "playbooks";

type TabDef = {
  id: TabId;
  label: string;
};

const TABS: TabDef[] = [
  { id: "chat", label: "Chat" },
  { id: "skills", label: "Skills" },
  { id: "playbooks", label: "Playbooks" },
];

type TabStripProps = {
  activeTab: TabId;
  onTabChange: (id: TabId) => void;
};

export const TabStrip: React.FC<TabStripProps> = ({
  activeTab,
  onTabChange,
}) => {
  return (
    <nav className="lq-tabstrip" role="tablist" aria-label="LQ.AI task pane tabs">
      {TABS.map((tab) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            aria-controls={`lq-tabpanel-${tab.id}`}
            id={`lq-tab-${tab.id}`}
            tabIndex={isActive ? 0 : -1}
            className={`lq-tab${isActive ? " lq-tab-active" : ""}`}
            onClick={() => onTabChange(tab.id)}
          >
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
};
