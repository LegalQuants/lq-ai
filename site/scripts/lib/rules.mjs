// The parts of Annex A's failure tests (docs/contribute/mini-prds/docsite/
// annex-a-quality-rules.md) a script can check on the built site. Iris's rules
// 10, 11 and 12; `check:rules` applies them to dist/, and these pure functions
// are what test/rules.test.mjs pins.

/**
 * Rule 10 — "Give every page an onward route": the other pages of the site a
 * page's own text links to. Its own anchors, the machine surface and
 * repository links don't count; a sidebar or a pagination link isn't part of
 * the page's text either, so callers pass only the content column's hrefs.
 */
export function onwardRoutes(hrefs, { route, base, known }) {
  const onward = new Set();
  for (const href of hrefs) {
    if (!href?.startsWith(base)) continue;
    const target = href.slice(base.length).split('#')[0].split('?')[0].replace(/\.md$/, '').replace(/\/+$/, '');
    if (target === route || target.startsWith('_') || !known.has(target)) continue;
    onward.add(target);
  }
  return onward;
}

/**
 * Programs a shell block runs that a reader can't take for granted. Builtins
 * and the commonest file utilities are assumed; anything else — git, jq,
 * docker, cosign — is a tool the reader has to have.
 */
const ASSUMED = new Set(
  ('cd echo export cat ls mkdir cp mv rm grep sed awk head tail chmod chown sudo set unset ' +
    'source test sleep wc sort uniq tr cut tee xargs find env true false printf read exec ' +
    'if then else elif fi for in do done while case esac exit cmp diff touch ln pwd date ' +
    'mktemp base64 which command').split(' ')
);

/**
 * Lines of a shell block → the programs it runs (first word of each command).
 * A line ending in `\` continues onto the next; `#` starts a comment; a `$` or
 * `%` prompt is dropped.
 */
export function shellPrograms(lines) {
  const programs = new Set();
  const commands = [];
  let pending = '';
  for (const raw of lines) {
    const line = raw.trim();
    if (pending === '' && line.startsWith('#')) continue;
    pending += `${line.replace(/\\$/, '')} `;
    if (!line.endsWith('\\')) { commands.push(pending.trim()); pending = ''; }
  }
  if (pending) commands.push(pending.trim());
  for (const command of commands) {
    const line = command.replace(/^[$%]\s+/, '').replace(/\s#.*$/, '');
    if (!line) continue;
    for (const part of line.split(/\|\||&&|\||;/)) {
      const words = part.trim().replace(/^[({]\s*/, '').split(/\s+/).filter((word) => !/^[A-Za-z_][A-Za-z0-9_]*=/.test(word));
      const program = words[0] === 'sudo' ? words[1] : words[0];
      if (program && /^[a-z][\w.-]*$/.test(program) && !ASSUMED.has(program)) programs.add(program);
    }
  }
  return programs;
}

/**
 * Rule 12 — "no assumed tools": a program a page's commands run that its text
 * never names. The page has to say the reader needs it.
 */
export function unnamedTools(programs, prose) {
  const text = prose.toLowerCase();
  return [...programs].filter((program) => !new RegExp(`(^|[^\\w-])${program.toLowerCase().replace(/[.]/g, '\\.')}([^\\w-]|$)`).test(text));
}

/**
 * Rule 11's lookup — where `llms.txt` lists each page: route → the headings
 * above it (`['Security & privacy', 'Review the evidence']`). A route listed
 * twice keeps every place, so a caller can see it has two homes.
 */
export function llmsPlaces(text, siteBase) {
  const places = new Map();
  const headings = [];
  for (const line of text.split('\n')) {
    const heading = /^(#{2,3}) (.+)$/.exec(line);
    if (heading) {
      headings.length = heading[1].length - 2;
      headings.push(heading[2].trim());
      continue;
    }
    const entry = /^- \[[^\]]*\]\(([^)]+)\)/.exec(line);
    if (!entry || !entry[1].startsWith(siteBase)) continue;
    const route = entry[1].slice(siteBase.length).replace(/\.md$/, '').replace(/\/+$/, '').replace(/^index$/, '');
    if (!places.has(route)) places.set(route, []);
    places.get(route).push([...headings]);
  }
  return places;
}
