/** `_guides/index.json` (scripts/gen-guide-details.mjs), loaded once per page. */
export interface GuideEntry {
  title: string; url: string; status: string; kind: string; kindLabel: string | null;
  description: string; audience: string[]; sections: { id: string; title: string }[];
  checkedAgainst: { sha: string; date: string; href: string; release: string | null } | null;
  sources: { path: string; href: string }[];
  pathway: string | null; governance: boolean; markdown: string;
}
export interface GuideIndex { schemaVersion: 2; base: string; pages: Record<string, GuideEntry> }

let loading: Promise<GuideIndex> | undefined;

export function loadGuides(base: string): Promise<GuideIndex> {
  loading ??= fetch(`${base}_guides/index.json`).then(async (response) => {
    if (!response.ok) throw new Error('Guide details unavailable');
    const index = await response.json();
    if (index.schemaVersion !== 2 || index.base !== base) throw new Error('Guide details do not match this build');
    return index as GuideIndex;
  }).catch((error) => { loading = undefined; throw error; });
  return loading;
}
