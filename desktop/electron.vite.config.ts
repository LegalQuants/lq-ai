import { defineConfig } from 'electron-vite'
import { resolve } from 'node:path'

export default defineConfig({
	main: { build: { rollupOptions: { input: resolve('src/main/index.ts') } } },
	preload: { build: { rollupOptions: { input: resolve('src/preload/index.ts') } } },
	renderer: {
		root: 'src/renderer',
		build: { rollupOptions: { input: resolve('src/renderer/index.html') } }
	}
})
