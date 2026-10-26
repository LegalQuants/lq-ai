/** Audit literal URLs and reject success when any route was skipped. */
export async function auditRoutes(urls, options, pa11yCi) {
  if (urls.length === 0 || new Set(urls).size !== urls.length) {
    throw new Error('a11y: expected a non-empty list of unique routes');
  }
  const report = await pa11yCi(urls, options);
  const checked = Object.keys(report.results ?? {});
  if (report.total !== urls.length || checked.length !== urls.length ||
      urls.some((url) => !Object.hasOwn(report.results, url))) {
    throw new Error(`a11y: incomplete route coverage (${checked.length}/${urls.length} results)`);
  }
  // Browser/navigation errors may not increment report.errors, but they do
  // leave passes below total. Match the CLI's zero-threshold failure rule.
  return report.passes === report.total ? 0 : 2;
}
