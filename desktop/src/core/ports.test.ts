import { describe, it, expect } from 'vitest'
import { resolvePorts } from './ports'
import { DEFAULT_PORTS } from './types'

describe('resolvePorts', () => {
	it('returns the defaults unchanged when every port is free', () => {
		const out = resolvePorts(DEFAULT_PORTS, () => true)
		expect(out).toEqual(DEFAULT_PORTS)
	})

	it('bumps a busy port to the next free one', () => {
		const busy = new Set([13012, 13013])
		const out = resolvePorts(DEFAULT_PORTS, (port) => !busy.has(port))
		expect(out.web).toBe(13014)
	})

	it('never assigns the same port to two services', () => {
		// pretend everything from defaults..+1 is busy so each must hunt upward
		const out = resolvePorts(DEFAULT_PORTS, (port) => port % 2 === 0)
		const values = Object.values(out)
		expect(new Set(values).size).toBe(values.length)
	})
})
