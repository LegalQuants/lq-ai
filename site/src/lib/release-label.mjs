/**
 * The release a page describes, in words, beside its "Checked against" commit
 * (`releaseOf` in scripts/lib/git.mjs supplies the tag). A reader running
 * v0.9.0 can see whether the page is about their version without reading a
 * commit hash. A release-note page (`notes`) names the release it records.
 * Undefined when the build had no release to name.
 */
export function releaseLabel(checkedAgainst) {
  const release = checkedAgainst?.release;
  if (!release) return undefined;
  if (checkedAgainst.notes) {
    return checkedAgainst.released ? `Release notes for ${release}` : `Release notes for ${release} (not yet released)`;
  }
  return checkedAgainst.released
    ? `Applies to ${release} and later`
    : `Newer than ${release} (not yet released)`;
}
