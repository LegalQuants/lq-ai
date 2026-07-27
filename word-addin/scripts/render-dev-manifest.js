#!/usr/bin/env node
/* eslint-env node */
/**
 * Renders manifest.xml with the same 4 tokens api/app/api/word_addin.py's
 * render_manifest() substitutes for the M365 Admin Center operator flow —
 * but pointed at the local Vite dev server instead of a real deployment,
 * so contributors can sideload without running the full API stack.
 *
 * Output: word-addin/manifest.dev.xml (gitignored).
 */

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const TEMPLATE_PATH = path.resolve(__dirname, "..", "manifest.xml");
const OUTPUT_PATH = path.resolve(__dirname, "..", "manifest.dev.xml");
const DEV_ORIGIN = "https://localhost:3001";

const substitutions = {
  ADDIN_ID: crypto.randomUUID(),
  DEPLOYMENT_ORIGIN: DEV_ORIGIN,
  DEPLOYMENT_DISPLAY_NAME: "LQ.AI (dev)",
  PROVIDER_NAME: "LegalQuants (dev)",
};

const template = fs.readFileSync(TEMPLATE_PATH, "utf-8");

const rendered = template.replace(/\{\{\s*(\w+)\s*\}\}/g, (match, name) => {
  if (!(name in substitutions)) {
    throw new Error(
      `manifest.xml references unknown token "${name}"; known tokens: ${Object.keys(substitutions).sort().join(", ")}`,
    );
  }
  return substitutions[name];
});

fs.writeFileSync(OUTPUT_PATH, rendered);
console.log(`Wrote ${OUTPUT_PATH} pointed at ${DEV_ORIGIN}`);
