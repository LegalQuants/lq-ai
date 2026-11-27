import { defineConfig } from "vitest/config";
import { resolve } from "path";
import pkg from "./package.json" with { type: "json" };

/**
 * Vitest config for the Word add-in.
 *
 * Tests target the React + TypeScript task-pane modules. The `jsdom`
 * environment provides `window` + `localStorage` so the auth helpers
 * can be exercised without a real browser. Office.js is mocked per-test
 * via `vi.stubGlobal`; do NOT load the Office.js library in tests.
 *
 * `__ADDIN_VERSION__` is the same compile-time global Vite's `define`
 * config injects (see vite.config.ts). Vitest gets the equivalent here
 * so version.ts's default-param can resolve at test time.
 *
 * `resolve.alias` mirrors vite.config.ts's `@` -> `src` alias — this
 * config is standalone (vitest doesn't inherit vite.config.ts), so
 * every source file that imports via `@/...` needs it repeated here or
 * tests fail to resolve those imports.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/__tests__/**/*.{test,spec}.{ts,tsx}"],
    globals: true,
  },
  define: {
    __ADDIN_VERSION__: JSON.stringify(pkg.version),
  },
});
