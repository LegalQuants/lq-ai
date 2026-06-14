import { describe, it, expect } from 'vitest'
import { dockerSearchPath, DOCKER_BIN_DIRS } from './dockerPath'

describe('dockerSearchPath', () => {
	it('prepends the docker bin dirs to the inherited PATH', () => {
		const out = dockerSearchPath('/usr/bin:/bin')
		expect(out.split(':').slice(0, DOCKER_BIN_DIRS.length)).toEqual(DOCKER_BIN_DIRS)
		expect(out.endsWith('/usr/bin:/bin')).toBe(true)
	})

	it('de-duplicates dirs already present in the inherited PATH', () => {
		const out = dockerSearchPath('/usr/local/bin:/usr/bin')
		expect(out.split(':').filter((d) => d === '/usr/local/bin')).toHaveLength(1)
	})

	it('handles an empty/undefined inherited PATH (GUI-launch minimal env)', () => {
		expect(dockerSearchPath('')).toBe(DOCKER_BIN_DIRS.join(':'))
		expect(dockerSearchPath()).toBe(DOCKER_BIN_DIRS.join(':'))
	})

	it('drops empty segments', () => {
		expect(dockerSearchPath('::/usr/bin:').split(':')).not.toContain('')
	})
})
