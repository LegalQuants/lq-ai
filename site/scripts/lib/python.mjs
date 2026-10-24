/**
 * Calling `gen-config-reference.py` from the Node build.
 *
 * The Python side parses; this side renders. Keeping the split means the
 * reference pages are built from what Python itself sees in the source, not
 * from a JavaScript approximation of Python syntax.
 *
 * `python3` is a hard dependency of the docs build and the CI workflow installs
 * it. When it is missing the generators do not crash the build silently — they
 * report it, and the page says the reference could not be generated, which is
 * a visible failure rather than an empty table.
 */

import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { REPO_ROOT } from './paths.mjs';

const SCRIPT = fileURLToPath(new URL('../gen-config-reference.py', import.meta.url));

/**
 * Parse Pydantic models out of Python source files.
 *
 * @param {string[]} relPaths repository-relative `.py` files
 * @returns {{ files: object[], problems: string[] }}
 */
export function parsePythonModels(relPaths) {
  try {
    const stdout = execFileSync(
      process.env.PYTHON || 'python3',
      [SCRIPT, REPO_ROOT, ...relPaths],
      { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, cwd: path.dirname(SCRIPT) }
    );
    return JSON.parse(stdout);
  } catch (error) {
    return {
      files: [],
      problems: [
        `gen-config-reference.py could not be run (${error.message.split('\n')[0]}) — python3 is required to build the reference pages`,
      ],
    };
  }
}

/**
 * Python docstrings are reStructuredText: ``literal`` is a code span there and
 * an empty code span in Markdown. Convert it, and nothing else — the text is
 * the repository's own words and the page should not paraphrase it.
 */
export const fromRst = (text) =>
  String(text ?? '')
    .replace(/``([^`]+)``/g, '`$1`')
    .replace(/:class:`~?([^`]+)`/g, '`$1`')
    .replace(/:attr:`~?([^`]+)`/g, '`$1`')
    .trim();
