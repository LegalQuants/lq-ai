import { describe, expect, it } from 'vitest';
import { TABS, isTabVisible, isTabAvailable, activeTabFor, type TabId, type User, type TabVisibilityOpts } from '../tabs';

describe('tabs', () => {
  const adminUser: User = { id: '1', email: 'a@x.io', is_admin: true, must_change_password: false, role: 'admin' };
  const memberUser: User = { id: '2', email: 'm@x.io', is_admin: false, must_change_password: false, role: 'member' };

  it('defines nine core tabs plus autonomous (opt-in) and admin (tabular added in M3-C3, autonomous added in M4-C2)', () => {
    const ids = TABS.map((t) => t.id);
    expect(ids).toEqual([
      'home',
      'chats',
      'matters',
      'skills',
      'knowledge',
      'playbooks',
      'tabular',
      'saved-prompts',
      'learn',
      'autonomous',
      'admin'
    ]);
  });

  it('hides admin tab for non-admin users', () => {
    expect(isTabVisible('admin', memberUser)).toBe(false);
    expect(isTabVisible('admin', adminUser)).toBe(true);
  });

  // Autonomous tab — opt-in gated (M4-C2)
  it('hides autonomous tab when autonomousEnabled is false', () => {
    expect(isTabVisible('autonomous', memberUser, { autonomousEnabled: false })).toBe(false);
  });
  it('shows autonomous tab when autonomousEnabled is true', () => {
    expect(isTabVisible('autonomous', memberUser, { autonomousEnabled: true })).toBe(true);
  });
  it('hides autonomous tab when no opts provided (defaults to off)', () => {
    expect(isTabVisible('autonomous', memberUser)).toBe(false);
  });

  it('shows core tabs to all users', () => {
    for (const id of [
      'home',
      'chats',
      'matters',
      'skills',
      'knowledge',
      'playbooks',
      'tabular',
      'saved-prompts'
    ] as TabId[]) {
      expect(isTabVisible(id, memberUser)).toBe(true);
      expect(isTabVisible(id, adminUser)).toBe(true);
    }
  });

  it('marks tabular tab as available (M3-C3)', () => {
    expect(isTabAvailable('tabular')).toBe(true);
  });

  it('activeTabFor recognises /lq-ai/tabular subroutes', () => {
    expect(activeTabFor('/lq-ai/tabular')).toBe('tabular');
    expect(activeTabFor('/lq-ai/tabular/new')).toBe('tabular');
    expect(activeTabFor('/lq-ai/tabular/abc-123')).toBe('tabular');
  });

  it('marks every M1 tab as available (last placeholder closed)', () => {
    expect(isTabAvailable('home')).toBe(true);
    expect(isTabAvailable('skills')).toBe(true);
    expect(isTabAvailable('admin')).toBe(true);
    expect(isTabAvailable('chats')).toBe(true);
    expect(isTabAvailable('matters')).toBe(true);
    // saved-prompts route landed pre-v0.1.0 (Saved Prompts page wraps the
    // SavedPromptsPanel — same backend, full-width browse view).
    expect(isTabAvailable('saved-prompts')).toBe(true);
    // Knowledge surface landed in Wave C — closes the last M1 placeholder.
    expect(isTabAvailable('knowledge')).toBe(true);
    // Learn surface landed in Wave C alongside Knowledge.
    expect(isTabAvailable('learn')).toBe(true);
    // Playbooks surface landed in M3-A4.
    expect(isTabAvailable('playbooks')).toBe(true);
  });

  it('derives active tab from pathname', () => {
    expect(activeTabFor('/lq-ai')).toBe('home');
    expect(activeTabFor('/lq-ai/skills')).toBe('skills');
    expect(activeTabFor('/lq-ai/skills/new')).toBe('skills');
    expect(activeTabFor('/lq-ai/skills/abc-123')).toBe('skills');
    expect(activeTabFor('/lq-ai/admin/audit-log')).toBe('admin');
    expect(activeTabFor('/lq-ai/login')).toBe(null);
    expect(activeTabFor('/lq-ai/change-password')).toBe(null);
  });

  // Three-role gating — spec §4.1.1
  const viewerUser: User = { ...memberUser, role: 'viewer', is_admin: false };
  const adminUserNoRole: User = { ...adminUser, role: 'admin' };

  it('hides admin tab for viewer role', () => {
    expect(isTabVisible('admin', viewerUser)).toBe(false);
  });
  it('hides admin tab for member role', () => {
    expect(isTabVisible('admin', { ...memberUser, role: 'member' })).toBe(false);
  });
  it('shows admin tab for admin role even if is_admin flag is stale', () => {
    expect(isTabVisible('admin', { ...adminUserNoRole, is_admin: false })).toBe(true);
  });
});
