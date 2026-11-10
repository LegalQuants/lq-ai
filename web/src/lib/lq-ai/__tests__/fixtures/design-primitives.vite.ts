import { defineConfig } from 'vite';
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

// From web/: npx vite --config src/lib/lq-ai/__tests__/fixtures/design-primitives.vite.ts
// Open /src/lib/lq-ai/__tests__/fixtures/design-primitives.html.
// Isolated UI fixture: no application routes, auth, backend or production configuration changes.
export default defineConfig({
	root: fileURLToPath(new URL('../../../../../', import.meta.url)),
	plugins: [svelte({ configFile: false, preprocess: vitePreprocess() })],
	resolve: { alias: { $lib: fileURLToPath(new URL('../../../', import.meta.url)) } },
	server: { host: '127.0.0.1', port: 33183, strictPort: true }
});
