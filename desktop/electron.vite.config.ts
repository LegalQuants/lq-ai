import { defineConfig } from 'electron-vite'
import { resolve } from 'node:path'

export default defineConfig({
	main: {
		define: {
			__LQ_AI_RELEASE_IMAGE_TAG__: JSON.stringify(process.env.LQ_AI_RELEASE_IMAGE_TAG ?? 'latest')
		},
		build: { rollupOptions: { input: resolve('src/main/index.ts') } }
	},
	preload: { build: { rollupOptions: { input: resolve('src/preload/index.ts') } } },
	renderer: {
		root: 'src/renderer',
		build: { rollupOptions: { input: resolve('src/renderer/index.html') } }
	}
})
