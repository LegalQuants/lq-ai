import { defineConfig } from 'vitest/config'

export default defineConfig({
	test: {
		environment: 'node',
		include: ['src/core/**/*.test.ts', 'src/main/orchestrator.test.ts']
	}
})
