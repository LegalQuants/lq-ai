/**
 * Top-tab definitions for the /lq-ai/* shell.
 *
 * Visibility = whether the user is allowed to see the tab at all (role gate).
 * Available  = whether the tab's destination route exists yet (per Wave A
 *              of the M1 frontend redesign; subsequent waves flip these to
 *              true as they ship the destination surfaces).
 *
 * Tabs that are visible-but-not-available open a ComingSoonModal that
 * points at the design spec.
 */

export type TabId =
  | 'home'
  | 'chats'
  | 'matters'
  | 'skills'
  | 'knowledge'
  | 'playbooks'
  | 'tabular'
  | 'saved-prompts'
  | 'learn'
  | 'admin';

export interface TabDef {
  id: TabId;
  label: string;
  icon: string;            // emoji used in mockups; replaced with sprite in Wave F polish
  route: string;
  adminOnly?: boolean;
  available: boolean;
  /** The wave that lands the destination route. Used by ComingSoonModal copy. */
  shipsInWave?: 'B' | 'C' | 'D' | 'E';
}

export interface User {
  id: string;
  email: string;
  is_admin: boolean;
  must_change_password: boolean;
  role?: 'admin' | 'member' | 'viewer';
}

export const TABS: readonly TabDef[] = [
  { id: 'home',          label: 'Home',          icon: '🏠', route: '/lq-ai',                available: true },
  { id: 'chats',         label: 'Chats',         icon: '💬', route: '/lq-ai/chats',          available: true },
  { id: 'matters',       label: 'Matters',       icon: '📁', route: '/lq-ai/matters',        available: true },
  { id: 'skills',        label: 'Skills',        icon: '🛠️', route: '/lq-ai/skills',         available: true },
  { id: 'knowledge',     label: 'Knowledge',     icon: '📎', route: '/lq-ai/knowledge',      available: true },
  { id: 'playbooks',     label: 'Playbooks',     icon: '📋', route: '/lq-ai/playbooks',      available: true },
  { id: 'tabular',       label: 'Tabular',       icon: '📊', route: '/lq-ai/tabular',        available: true },
  { id: 'saved-prompts', label: 'Saved Prompts', icon: '📌', route: '/lq-ai/saved-prompts',  available: true },
  { id: 'learn',         label: 'Learn',         icon: '📖', route: '/lq-ai/learn',           available: true },
  { id: 'admin',         label: 'Admin',         icon: '🛡',  route: '/lq-ai/admin/audit-log', adminOnly: true, available: true }
] as const;

export function isTabVisible(id: TabId, user: User | null): boolean {
  const tab = TABS.find((t) => t.id === id);
  if (!tab) return false;
  if (tab.adminOnly) {
    return user?.role === 'admin' || user?.is_admin === true;
  }
  return true;
}

export function isTabAvailable(id: TabId): boolean {
  return TABS.find((t) => t.id === id)?.available ?? false;
}

/** Returns the tab whose route is the deepest prefix of pathname, or null on auth-exempt routes. */
export function activeTabFor(pathname: string): TabId | null {
  if (pathname === '/lq-ai/login' || pathname === '/lq-ai/change-password') return null;
  if (pathname === '/lq-ai' || pathname === '/lq-ai/') return 'home';

  // Find tab whose route is the deepest prefix.
  let best: TabDef | null = null;
  for (const tab of TABS) {
    if (tab.id === 'home') continue;
    if (pathname === tab.route || pathname.startsWith(tab.route + '/')) {
      if (!best || tab.route.length > best.route.length) best = tab;
    }
  }
  return best?.id ?? 'home';
}
