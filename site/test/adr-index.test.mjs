import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { statusOf } from '../scripts/gen-adr-index.mjs';

describe('ADR index status line', () => {
  it('reads every form the ADRs write it in', () => {
    const forms = {
      bold: '# ADR 0043\n\n**Status:** Accepted (2026-10-18)\n',
      'bold, no colon': '# ADR\n\n**Status** Proposed\n',
      'bold list item': '# ADR 0044\n\n- **Status:** Accepted (2026-10-18) — committee adoption.\n- **Draft date:** 2026-10-08.\n',
      'starred list item': '# ADR\n\n* **Status:** Superseded by 0050\n',
      'table row': '# ADR\n\n| Field | Value |\n|---|---|\n| Status | Accepted |\n',
      plain: '# ADR\n\nStatus: Rejected\n',
      'plain list item': '# ADR\n\n- Status: Deferred\n',
    };
    const expected = {
      bold: 'Accepted (2026-10-18)',
      'bold, no colon': 'Proposed',
      'bold list item': 'Accepted (2026-10-18) — committee adoption.',
      'starred list item': 'Superseded by 0050',
      'table row': 'Accepted',
      plain: 'Rejected',
      'plain list item': 'Deferred',
    };
    for (const [form, text] of Object.entries(forms)) assert.equal(statusOf(text), expected[form], form);
  });

  it('reports a file with no status line rather than guessing', () => {
    assert.equal(statusOf('# ADR\n\nThe status quo is fine.\n'), undefined);
  });
});
