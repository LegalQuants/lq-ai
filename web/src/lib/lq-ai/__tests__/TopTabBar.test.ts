import { describe, expect, it } from 'vitest';
import { visibleTabsFor, type TopTabBarUser } from '../components/TopTabBar.svelte';

describe('TopTabBar.visibleTabsFor', () => {
  const admin: TopTabBarUser = { id: '1', email: 'a@x', is_admin: true,  must_change_password: false };
  const member: TopTabBarUser = { id: '2', email: 'm@x', is_admin: false, must_change_password: false };

  it('returns eight tabs for a non-admin user (admin hidden, playbooks added in M3-A4)', () => {
    const ids = visibleTabsFor(member).map((t) => t.id);
    expect(ids).toEqual(['home', 'chats', 'matters', 'skills', 'knowledge', 'playbooks', 'saved-prompts', 'learn']);
  });

  it('returns nine tabs for an admin user (playbooks added in M3-A4)', () => {
    const ids = visibleTabsFor(admin).map((t) => t.id);
    expect(ids).toEqual(['home', 'chats', 'matters', 'skills', 'knowledge', 'playbooks', 'saved-prompts', 'learn', 'admin']);
  });

  it('returns eight tabs for null user (treats as non-admin, playbooks added in M3-A4)', () => {
    const ids = visibleTabsFor(null).map((t) => t.id);
    expect(ids).toEqual(['home', 'chats', 'matters', 'skills', 'knowledge', 'playbooks', 'saved-prompts', 'learn']);
  });
});
