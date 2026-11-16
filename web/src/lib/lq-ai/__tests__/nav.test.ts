import { describe, expect, it } from 'vitest';
import {
  NAV,
  activeNavItemFor,
  allNavItems,
  isNavItemVisible,
  visibleNav,
  type NavItemId
} from '../nav';
import { TABS, isTabVisible, type TabId, type TabVisibilityOpts, type User } from '../tabs';

const admin: User = { id: '1', email: 'a@x.io', is_admin: true, must_change_password: false, role: 'admin' };
const legacyAdmin: User = { id: '4', email: 'l@x.io', is_admin: true, must_change_password: false };
const member: User = { id: '2', email: 'm@x.io', is_admin: false, must_change_password: false, role: 'member' };
const viewer: User = { id: '3', email: 'v@x.io', is_admin: false, must_change_password: false, role: 'viewer' };
const users: Array<[string, User | null]> = [
  ['admin', admin],
  ['legacy admin', legacyAdmin],
  ['member', member],
  ['viewer', viewer],
  ['signed out', null]
];
const optsVariants: TabVisibilityOpts[] = [{}, { autonomousEnabled: false }, { autonomousEnabled: true }];

/** Destinations both models know. */
const counterparts: Array<[TabId, NavItemId]> = [
  ['home', 'home'],
  ['chats', 'all-chats'],
  ['matters', 'all-matters'],
  ['skills', 'skills'],
  ['knowledge', 'knowledge'],
  ['playbooks', 'playbooks'],
  ['tabular', 'tabular'],
  ['saved-prompts', 'saved-prompts'],
  ['learn', 'learn'],
  ['autonomous', 'labs'],
  ['admin', 'admin']
];

describe('sidebar navigation model', () => {
  it('follows the redesign order: New, then Home, Tabular, Labs, Customise, matters, chats, foot', () => {
    expect(NAV.map((s) => s.id)).toEqual(['top', 'primary', 'matters', 'chats', 'foot']);
    expect(NAV[1].items.map((i) => i.id)).toEqual(['home', 'tabular', 'labs', 'customise']);
    expect(NAV[4].items.map((i) => i.id)).toEqual(['learn', 'trust', 'admin', 'account']);
  });

  it('groups Skills, Knowledge, Playbooks and Saved prompts under Customise', () => {
    const customise = NAV[1].items.find((i) => i.id === 'customise');
    expect(customise?.children?.map((c) => c.id)).toEqual(['skills', 'knowledge', 'playbooks', 'saved-prompts']);
  });

  it('has unique ids and only /lq-ai routes', () => {
    const items = allNavItems();
    const ids = items.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const item of items) expect(item.route === '/lq-ai' || item.route.startsWith('/lq-ai/')).toBe(true);
  });

  it('covers every destination the tab row offers today', () => {
    const navRoutes = new Set(allNavItems().map((i) => i.route));
    for (const tab of TABS) expect(navRoutes.has(tab.route), tab.route).toBe(true);
  });

  it('explains every placeholder route with a note', () => {
    for (const id of ['labs', 'admin'] as NavItemId[]) {
      const item = allNavItems().find((i) => i.id === id);
      expect(item?.note).toMatch(/P2\./);
    }
  });
});

describe('sidebar visibility', () => {
  it('shows Admin to admins only, including the legacy flag', () => {
    expect(isNavItemVisible('admin', admin)).toBe(true);
    expect(isNavItemVisible('admin', legacyAdmin)).toBe(true);
    expect(isNavItemVisible('admin', member)).toBe(false);
    expect(isNavItemVisible('admin', viewer)).toBe(false);
    expect(isNavItemVisible('admin', null)).toBe(false);
  });

  it('shows Labs only when the Autonomous opt-in is on, and treats unknown as off', () => {
    expect(isNavItemVisible('labs', member, { autonomousEnabled: true })).toBe(true);
    expect(isNavItemVisible('labs', member, { autonomousEnabled: false })).toBe(false);
    expect(isNavItemVisible('labs', member)).toBe(false);
    expect(isNavItemVisible('labs', admin)).toBe(false);
  });

  it('shows the core rows to every user', () => {
    for (const [, user] of users) {
      for (const id of ['new', 'home', 'tabular', 'customise', 'skills', 'all-matters', 'all-chats', 'learn', 'trust', 'account'] as NavItemId[]) {
        expect(isNavItemVisible(id, user), id).toBe(true);
      }
    }
  });

  it('agrees with the tab row for every destination both know', () => {
    for (const [, user] of users) {
      for (const opts of optsVariants) {
        for (const [tabId, navId] of counterparts) {
          expect(isNavItemVisible(navId, user, opts), `${tabId}/${navId}`).toBe(isTabVisible(tabId, user, opts));
        }
      }
    }
  });

  it('drops hidden rows and keeps section order', () => {
    const memberNav = visibleNav(member);
    expect(memberNav.map((s) => s.id)).toEqual(['top', 'primary', 'matters', 'chats', 'foot']);
    expect(memberNav[1].items.map((i) => i.id)).toEqual(['home', 'tabular', 'customise']);
    expect(memberNav[4].items.map((i) => i.id)).toEqual(['learn', 'trust', 'account']);

    const adminNav = visibleNav(admin, { autonomousEnabled: true });
    expect(adminNav[1].items.map((i) => i.id)).toEqual(['home', 'tabular', 'labs', 'customise']);
    expect(adminNav[4].items.map((i) => i.id)).toEqual(['learn', 'trust', 'admin', 'account']);
  });

  it('returns false for an unknown id', () => {
    expect(isNavItemVisible('nope' as NavItemId, admin)).toBe(false);
  });
});

describe('activeNavItemFor', () => {
  it.each([
    ['/lq-ai', 'home'],
    ['/lq-ai/', 'home'],
    ['/lq-ai/chats', 'all-chats'],
    ['/lq-ai/matters', 'all-matters'],
    ['/lq-ai/matters/m1', 'all-matters'],
    ['/lq-ai/skills/s1/edit', 'skills'],
    ['/lq-ai/knowledge', 'knowledge'],
    ['/lq-ai/playbooks/easy', 'playbooks'],
    ['/lq-ai/saved-prompts', 'saved-prompts'],
    ['/lq-ai/tabular/bulk-ops/op1', 'tabular'],
    ['/lq-ai/learn/how', 'learn'],
    ['/lq-ai/trust', 'trust'],
    ['/lq-ai/autonomous/schedules', 'labs'],
    ['/lq-ai/admin/models', 'admin'],
    ['/lq-ai/admin/audit-log', 'admin'],
    ['/lq-ai/settings/appearance', 'account'],
    ['/lq-ai/settings/account', 'account'],
    ['/lq-ai/word-addin/oauth-start', 'home']
  ])('%s → %s', (pathname, expected) => {
    expect(activeNavItemFor(pathname)).toBe(expected);
  });

  it('returns null on the routes without the shell', () => {
    expect(activeNavItemFor('/lq-ai/login')).toBeNull();
    expect(activeNavItemFor('/lq-ai/change-password')).toBeNull();
  });
});
