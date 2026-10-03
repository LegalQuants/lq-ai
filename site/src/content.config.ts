import { defineCollection, z } from 'astro:content';
import { docsLoader } from '@astrojs/starlight/loaders';
import { docsSchema } from '@astrojs/starlight/schema';

/**
 * Who a page is written for. A page may name more than one, but naming all of
 * them is the same as naming none — the chips exist to let a reader skip.
 */
export const AUDIENCES = [
  'operator',
  'evaluator',
  'author',
  'contributor',
  'partner',
  'agent',
] as const;

/**
 * Review state, rendered as a badge carrying its own text (never colour alone).
 * `draft` is the default so an unreviewed page cannot pass as reviewed by
 * omission.
 */
export const STATUSES = ['draft', 'reviewed'] as const;

export const collections = {
  docs: defineCollection({
    loader: docsLoader(),
    schema: docsSchema({
      extend: z.object({
        // --- written by the author, in docs/site/** -------------------------
        audience: z.array(z.enum(AUDIENCES)).optional(),
        status: z.enum(STATUSES).default('draft'),
        /**
         * Repository-relative canonical files this page curates or checks its
         * claims against. The stamp is the newest commit touching the page or
         * any of these, so a source that moves makes the stamp move.
         */
        sources: z.array(z.string()).default([]),

        // --- injected by `npm run sync`, never hand-written -----------------
        /** The commit the page was checked against, and its date. */
        checkedAgainst: z
          .object({
            sha: z.string(),
            date: z.string(),
          })
          .optional(),
        /**
         * The resolved source list the stamp rendered from. Separate from
         * `sources` so the transform can add the page's own path and drop
         * anything it could not resolve, without editing the author's list.
         */
        sourceFiles: z.array(z.string()).optional(),
      }),
    }),
  }),
};
