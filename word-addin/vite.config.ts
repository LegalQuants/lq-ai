/* eslint-env node */
/**
 * Vite config for the Word add-in.
 *
 * Replaces webpack.config.js — see docs/adr/0022-word-addin-vite-over-webpack.md
 * for why. Produces the same output shape webpack did:
 *
 *   web/static/word-addin/taskpane.html        — task pane shell loaded by Office.js
 *   web/static/word-addin/assets/taskpane-*.js  — React + TypeScript task pane
 *   web/static/word-addin/commands.html        — ribbon command surface
 *   web/static/word-addin/assets/commands-*.js  — Office.js command handlers
 *   web/static/word-addin/manifest.xml         — manifest copied as-is (templated at
 *                                                 install time by the LQ.AI admin UI;
 *                                                 see M3-B1 backend endpoint)
 *   web/static/word-addin/assets/icon-*.png     — icons referenced by manifest.xml
 */
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";
import { copyFileSync, cpSync } from "fs";
// office-addin-dev-certs is a plain CJS module (no default export) —
// a namespace import is the interop-safe form when Vite's config
// loader resolves this in an ESM context; a default import resolves
// to `undefined` here.
import * as devCerts from "office-addin-dev-certs";
import pkg from "./package.json";

const OUTPUT_DIR = resolve(__dirname, "..", "web", "static", "word-addin");

/** Copies manifest.xml + assets/ into the build output — the same two
 *  copy operations CopyWebpackPlugin did. Not worth a dependency
 *  (vite-plugin-static-copy) for two `fs` calls. Only runs for
 *  production builds (`vite build`); the dev server serves these
 *  straight from disk via `publicDir`-style static handling isn't
 *  needed since dev sideload only ever hits taskpane.html/commands.html
 *  through Vite's own module graph. */
function copyManifestAndAssets(): Plugin {
  return {
    name: "copy-manifest-and-assets",
    apply: "build",
    closeBundle() {
      copyFileSync(resolve(__dirname, "manifest.xml"), resolve(OUTPUT_DIR, "manifest.xml"));
      cpSync(resolve(__dirname, "assets"), resolve(OUTPUT_DIR, "assets"), { recursive: true });
    },
  };
}

export default defineConfig(async ({ mode }) => {
  const isProduction = mode === "production";

  // Use the cert `office-addin-dev-certs install` generates and trusts,
  // not Vite's own self-signed cert — Word's embedded browser only
  // trusts the former. Same shape webpack-dev-server consumed this as.
  const httpsOptions = isProduction ? undefined : await devCerts.getHttpsServerOptions();

  return {
    plugins: [react(), copyManifestAndAssets()],
    resolve: {
      alias: {
        "@": resolve(__dirname, "src"),
      },
    },
    // Matches the SvelteKit route's serving path in production
    // (web/src/routes/word-addin/) so manifest.xml's SourceLocation —
    // `{{ DEPLOYMENT_ORIGIN }}/word-addin/taskpane.html` — resolves the
    // same way against both a real deployment and the Vite dev server.
    base: "/word-addin/",
    define: {
      // Inject the package.json version into the bundle as the
      // ``__ADDIN_VERSION__`` global. M3-B8's version handshake compares
      // this value against the deployment's compatibility range — bake
      // it in at build time so the runtime check can't be tricked by a
      // tampered API response.
      __ADDIN_VERSION__: JSON.stringify(pkg.version),
    },
    build: {
      outDir: OUTPUT_DIR,
      emptyOutDir: true,
      sourcemap: true,
      rollupOptions: {
        input: {
          taskpane: resolve(__dirname, "taskpane.html"),
          commands: resolve(__dirname, "commands.html"),
        },
      },
    },
    server: {
      port: 3001,
      https: httpsOptions,
      headers: { "Access-Control-Allow-Origin": "*" },
      // The dev-sideload manifest (npm run manifest:dev) points the task
      // pane at this dev server, so `window.location.origin` — what
      // `deploymentOrigin()` in auth.ts uses for every API call — resolves
      // to here, not to the `api` container. Proxy `/api` through to the
      // real backend (docker-compose's default host port) so login,
      // refresh, and the version handshake reach a live server instead of
      // 404ing against the dev server itself. Override with
      // LQ_AI_DEV_API_ORIGIN if your stack maps `api` to a different port.
      proxy: {
        "/api": {
          target: process.env.LQ_AI_DEV_API_ORIGIN || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
