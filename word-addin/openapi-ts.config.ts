import { defineConfig } from "@hey-api/openapi-ts";

/**
 * Generates a typed client from the backend's live OpenAPI spec — see
 * docs/api/backend-openapi.yaml for the hand-authored sketch and
 * docs/api/backend-openapi.generated.yaml for the committed export;
 * this points at the *live* dev server instead so it always reflects
 * exactly what the running `api` container has right now.
 *
 * `LQ_AI_OPENAPI_URL` mirrors `vite.config.ts`'s `LQ_AI_DEV_API_ORIGIN`
 * override for a non-default dev api port.
 *
 * Output is gitignored (src/generated/) — a build artifact, not
 * consumed by any hand-written code yet. Do not edit generated files
 * directly; regenerate via `npm run openapi-ts`.
 */
export default defineConfig({
  input: `${process.env.LQ_AI_OPENAPI_URL ?? "http://localhost:8000"}/openapi.json`,
  output: "src/generated",
  plugins: ["@hey-api/client-fetch"],
});
