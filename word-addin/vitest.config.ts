import { defineConfig } from "vitest/config";
import pkg from "./package.json" with { type: "json" };

/**
 * Vitest config for the Word add-in.
 *
 * Tests target the React + TypeScript task-pane modules. The `jsdom`
 * environment provides `window` + `localStorage` so the auth helpers
 * can be exercised without a real browser. Office.js is mocked per-test
 * via `vi.stubGlobal`; do NOT load the Office.js library in tests.
 *
 * `__ADDIN_VERSION__` is the same compile-time global webpack injects
 * via DefinePlugin in production builds. Vitest gets the equivalent
 * here so version.ts's default-param can resolve at test time.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/__tests__/**/*.{test,spec}.{ts,tsx}"],
    globals: true,
  },
  define: {
    __ADDIN_VERSION__: JSON.stringify(pkg.version),
  },
});
