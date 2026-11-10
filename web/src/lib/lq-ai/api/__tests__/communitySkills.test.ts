import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from '../client';
import { getCommunitySkill, installCommunitySkill, listCommunitySkills } from '../communitySkills';
vi.mock('../client', () => ({ apiRequest: vi.fn().mockResolvedValue({}) }));

describe('community skill distribution client', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});
	it('sends the reviewed hash and team as an object, serialized once by the client', async () => {
		await installCommunitySkill('lease-review', 'a'.repeat(64), 'team-1');
		expect(apiRequest).toHaveBeenCalledWith('/admin/community-skills/lease-review/install', {
			method: 'POST',
			body: { scope: 'team', owner_team_id: 'team-1', expected_review_hash: 'a'.repeat(64) }
		});
	});
	it('keeps personal installation independent of the selected team', async () => {
		await installCommunitySkill('lease-review', 'b'.repeat(64));
		expect(apiRequest).toHaveBeenCalledWith('/admin/community-skills/lease-review/install', {
			method: 'POST',
			body: { scope: 'user', owner_team_id: null, expected_review_hash: 'b'.repeat(64) }
		});
	});
	it('queries installation state for the receiving team', async () => {
		await listCommunitySkills('team-1');
		await getCommunitySkill('lease-review', 'team-1');
		expect(apiRequest).toHaveBeenCalledWith(
			'/admin/community-skills?scope=team&owner_team_id=team-1',
			{ method: 'GET' }
		);
		expect(apiRequest).toHaveBeenCalledWith(
			'/admin/community-skills/lease-review?scope=team&owner_team_id=team-1',
			{ method: 'GET' }
		);
	});
});
