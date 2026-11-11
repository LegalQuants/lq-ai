/**
 * Sidebar navigation model for the redesigned LQ.AI shell.
 *
 * Data only. Nothing renders from this file yet: `TopTabBar` keeps rendering
 * from `TABS` in `./tabs`. The left sidebar (interface-redesign work plan,
 * Annex B item P1.3) renders from `NAV`; the cutover that removes the tab row
 * retires `TABS`. Until then the two models share one visibility rule
 * (`isVisibleUnder`), and `nav.test.ts` checks that they agree for every
 * destination both know, so the gates the tab row enforces today (admin-only
 * rows, the Autonomous opt-in) cannot drift while the sidebar is built.
 *
 * The order and grouping follow the redesign decisions (CHANGES.md): C7 the
 * order, C8 Customise, C10 matters and chats in the sidebar, C11 "New" at the
 * top, C31 Trust & Privacy at the foot, C33 Labs. Rows whose destination does
 * not exist yet point at today's nearest route and carry a `note` naming the
 * Annex B item that replaces the placeholder.
 */
import { isVisibleUnder, type TabVisibilityOpts, type User, type VisibilityRule } from './tabs';

export type NavSectionId = 'top' | 'primary' | 'matters' | 'chats' | 'foot';

export type NavItemId =
  | 'new'
  | 'home'
  | 'tabular'
  | 'labs'
  | 'customise'
  | 'skills'
  | 'knowledge'
  | 'playbooks'
  | 'saved-prompts'
  | 'all-matters'
  | 'all-chats'
  | 'learn'
  | 'trust'
  | 'admin'
  | 'account';

export interface NavItem {
  id: NavItemId;
  label: string;
  route: string;
  visibility: VisibilityRule;
  /**
   * Route prefix that marks the row active, when it differs from `route`: a row
   * that opens one page of a section is active for the whole section.
   */
  matches?: string;
  /** Rows shown under an expanding group. A group is active when a child is. */
  children?: readonly NavItem[];
  /** Why the route or label is provisional, and which work item settles it. */
  note?: string;
}

export interface NavSection {
  id: NavSectionId;
  items: readonly NavItem[];
}

const customise: readonly NavItem[] = [
  { id: 'skills', label: 'Skills', route: '/lq-ai/skills', visibility: 'all' },
  { id: 'knowledge', label: 'Knowledge', route: '/lq-ai/knowledge', visibility: 'all' },
  { id: 'playbooks', label: 'Playbooks', route: '/lq-ai/playbooks', visibility: 'all' },
  { id: 'saved-prompts', label: 'Saved prompts', route: '/lq-ai/saved-prompts', visibility: 'all' }
];

export const NAV: readonly NavSection[] = [
  {
    id: 'top',
    items: [
      {
        id: 'new',
        label: 'New',
        route: '/lq-ai/chats',
        visibility: 'all',
        note: 'C11. Opens a new chat; the chat screen itself is P2.1.'
      }
    ]
  },
  {
    id: 'primary',
    items: [
      { id: 'home', label: 'Home', route: '/lq-ai', visibility: 'all' },
      { id: 'tabular', label: 'Tabular', route: '/lq-ai/tabular', visibility: 'all' },
      {
        id: 'labs',
        label: 'Labs',
        route: '/lq-ai/autonomous',
        visibility: 'autonomous',
        note:
          'C33. Placeholder route: P2.8 adds /lq-ai/labs. Visibility follows the Autonomous opt-in until the Labs ADR rules on per-lab switches (F5).'
      },
      {
        id: 'customise',
        label: 'Customise',
        route: '/lq-ai/skills',
        visibility: 'all',
        children: customise,
        note: 'C8. An expanding group, not a page; its route is the first child.'
      }
    ]
  },
  {
    id: 'matters',
    items: [
      {
        id: 'all-matters',
        label: 'All matters',
        route: '/lq-ai/matters',
        visibility: 'all',
        note: 'C10. Recent matters with their chats are listed above this row (P1.3).'
      }
    ]
  },
  {
    id: 'chats',
    items: [
      {
        id: 'all-chats',
        label: 'All chats',
        route: '/lq-ai/chats',
        visibility: 'all',
        note: 'C10. Chats outside a matter are listed above this row (P1.3).'
      }
    ]
  },
  {
    id: 'foot',
    items: [
      { id: 'learn', label: 'Learn', route: '/lq-ai/learn', visibility: 'all' },
      { id: 'trust', label: 'Trust & Privacy', route: '/lq-ai/trust', visibility: 'all', note: 'C31.' },
      {
        id: 'admin',
        label: 'Admin',
        route: '/lq-ai/admin/audit-log',
        matches: '/lq-ai/admin',
        visibility: 'admin',
        note: 'C54. Placeholder route: P2.10 adds the /lq-ai/admin overview.'
      },
      {
        id: 'account',
        label: 'Account settings',
        route: '/lq-ai/settings/account',
        matches: '/lq-ai/settings',
        visibility: 'all',
        note: 'C30. Replaces the top bar’s Appearance shortcut; Appearance stays a tab of this page.'
      }
    ]
  }
];

/** Every item, groups and their children alike, in sidebar order. */
export function allNavItems(sections: readonly NavSection[] = NAV): NavItem[] {
  const out: NavItem[] = [];
  for (const section of sections) {
    for (const item of section.items) {
      out.push(item);
      if (item.children) out.push(...item.children);
    }
  }
  return out;
}

export function findNavItem(id: NavItemId): NavItem | undefined {
  return allNavItems().find((item) => item.id === id);
}

export function isNavItemVisible(id: NavItemId, user: User | null, opts: TabVisibilityOpts = {}): boolean {
  const item = findNavItem(id);
  if (!item) return false;
  return isVisibleUnder(item.visibility, user, opts);
}

/**
 * The sections and rows this user may see, in order. Sections with nothing
 * visible are dropped; a group keeps only its visible children and is dropped
 * when none remain.
 */
export function visibleNav(user: User | null, opts: TabVisibilityOpts = {}): NavSection[] {
  const sections: NavSection[] = [];
  for (const section of NAV) {
    const items: NavItem[] = [];
    for (const item of section.items) {
      if (!isVisibleUnder(item.visibility, user, opts)) continue;
      if (item.children) {
        const children = item.children.filter((child) => isVisibleUnder(child.visibility, user, opts));
        if (children.length === 0) continue;
        items.push({ ...item, children });
      } else {
        items.push(item);
      }
    }
    if (items.length > 0) sections.push({ id: section.id, items });
  }
  return sections;
}

/**
 * The row whose route is the deepest prefix of `pathname`, or null on the
 * routes that render without the shell (sign-in, forced password change).
 * Mirrors `activeTabFor` in `./tabs`: anything under /lq-ai that no row claims
 * is Home. Rows that share a route (New and All chats) resolve to the list row.
 */
export function activeNavItemFor(pathname: string): NavItemId | null {
  if (pathname === '/lq-ai/login' || pathname === '/lq-ai/change-password') return null;
  if (pathname === '/lq-ai' || pathname === '/lq-ai/') return 'home';

  let best: { id: NavItemId; prefix: string } | null = null;
  for (const item of allNavItems()) {
    if (item.id === 'home' || item.id === 'new' || item.children) continue;
    const prefix = item.matches ?? item.route;
    if (pathname === prefix || pathname.startsWith(prefix + '/')) {
      if (!best || prefix.length > best.prefix.length) best = { id: item.id, prefix };
    }
  }
  return best?.id ?? 'home';
}
