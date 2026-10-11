/** Source selectors for Explore and task discovery; no answer strings live here. */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';
import { selectSection, scanLines } from './markdown.mjs';
import { SITE_BASE, SITE_URL, canonicalUrl, withBase } from './paths.mjs';

export const markdownUrl = (route) =>
  `${SITE_URL}${SITE_BASE}${route ? `${route}.md` : 'index.md'}`;

function exactKeys(object, required, optional = []) {
  if (!object || typeof object !== 'object' || Array.isArray(object)) throw new Error('expected a mapping');
  const unknown = Object.keys(object).filter((key) => ![...required, ...optional].includes(key));
  const missing = required.filter((key) => object[key] === undefined || object[key] === null);
  if (unknown.length || missing.length) throw new Error(`unknown keys: ${unknown.join(', ')}; missing keys: ${missing.join(', ')}`);
}

export function resolveViews({ dataDir, pages }) {
  const byRoute = new Map(pages.map((page) => [page.route, page]));
  const selected = (route, heading) => {
    const page = byRoute.get(route);
    if (!page) throw new Error(`unknown route ${JSON.stringify(route)}`);
    if (typeof heading !== 'string' || !/^#{1,6} /.test(heading)) throw new Error('section needs a Markdown heading');
    return { ...selectSection(page.markdown, heading), route, heading,
      title: page.title, url: canonicalUrl(route), markdownUrl: markdownUrl(route),
      status: page.status, sha: page.sha, date: page.date, sources: page.sources };
  };
  const load = (name, key) => {
    const file = path.join(dataDir, name);
    if (!existsSync(file)) return [];
    const data = YAML.parse(readFileSync(file, 'utf8'));
    exactKeys(data, ['schemaVersion', key]);
    if (data.schemaVersion !== 1 || !Array.isArray(data[key])) throw new Error(`${file}: unsupported schema`);
    return data[key];
  };
  const ids = new Set();
  const id = (value) => {
    if (typeof value !== 'string' || !/^[a-z][a-z0-9-]*$/.test(value) || ids.has(value)) {
      throw new Error(`invalid or duplicate view id ${JSON.stringify(value)}`);
    }
    ids.add(value);
    return value;
  };
  const questions = load('explore.yaml', 'questions').map((question) => {
    exactKeys(question, ['id', 'content'], ['label']);
    exactKeys(question.content, ['route', 'heading']);
    if (question.label !== undefined && (typeof question.label !== 'string' || !question.label.trim())) throw new Error('empty question label');
    const content = selected(question.content.route, question.content.heading);
    // A fragment copied into Explore belongs to its owning document, not to
    // the landing page. Other links already passed through the repo resolver.
    content.markdown = scanLines(content.markdown).map((entry) => entry.inFence
      ? entry.line
      : entry.line.replace(/\]\(#([^)]*)\)/g,
        (_match, fragment) => `](${withBase(content.route)}#${fragment})`)).join('\n');
    return { ...content, id: id(question.id), label: question.label ?? content.label };
  });
  const tasks = load('journeys.yaml', 'journeys').map((task) => {
    exactKeys(task, ['id', 'route', 'before', 'steps', 'check'], ['choices']);
    if (!Array.isArray(task.steps) || !task.steps.length) throw new Error('journey needs steps');
    if (task.choices !== undefined && !Array.isArray(task.choices)) throw new Error('journey choices must be a list');
    const page = byRoute.get(task.route);
    const before = selected(task.route, task.before);
    const verification = selected(task.route, task.check);
    const steps = task.steps.map((heading) => selected(task.route, heading));
    if (new Set(task.steps).size !== steps.length) throw new Error('duplicate journey step');
    const choiceIds = new Set();
    const choices = (task.choices ?? []).map((choice) => {
      exactKeys(choice, ['id', 'section']);
      if (typeof choice.id !== 'string' || choiceIds.has(choice.id)) throw new Error('invalid or duplicate choice');
      choiceIds.add(choice.id);
      const content = selected(task.route, choice.section);
      if (!/^Applicable when[: ]/m.test(content.markdown)) throw new Error(`choice ${choice.id} needs an applicability statement in its source section`);
      return { ...content, id: choice.id };
    });
    return { id: id(task.id), route: task.route, title: page.title,
      url: canonicalUrl(task.route), markdownUrl: markdownUrl(task.route),
      status: page.status, sha: page.sha, sources: page.sources,
      before, steps, choices, verification };
  });
  return { schemaVersion: 1, questions, tasks };
}

/** Discovery references point to complete docs instead of copying procedures. */
export function taskIndex(views) {
  const reference = ({ heading, label, markdownUrl }) => ({ heading, label, markdownUrl });
  return { schemaVersion: 1, tasks: views.tasks.map((task) => ({
    id: task.id, title: task.title, url: task.url, markdownUrl: task.markdownUrl,
    status: task.status, checkedAgainst: task.sha, sources: task.sources,
    prerequisites: reference(task.before), steps: task.steps.map(reference),
    alternatives: task.choices.map((choice) => ({ id: choice.id, ...reference(choice) })),
    verification: reference(task.verification),
  })) };
}
