/**
 * MarkdownContent — renders an assistant message's markdown, with
 * `citation:<n>` links (per `EMIT_ANSWER_TOOL`'s instruction in
 * `api/app/api/word_addin.py`) rendered as clickable inline `Anchor`s
 * instead of real hyperlinks. `<n>` indexes into the message's own
 * `citations` array (`DocumentChatCitation[]`, `domain/documentChat.ts`).
 *
 * Standard markdown link syntax carries the interactivity — no custom
 * remark plugin, no bespoke marker syntax to keep in sync with the
 * model's escaping/nesting behavior. A real link (any other `href`)
 * renders normally; only the `citation:` scheme is intercepted.
 *
 * `urlTransform`: react-markdown v9+ ships a `defaultUrlTransform` that
 * strips any href whose protocol isn't on its safe-list (http/https/
 * mailto/etc — an XSS defense against things like `javascript:` links).
 * `citation:` isn't on that list, so without this override react-markdown
 * silently rewrites every `citation:<n>` href to `""` *before* it ever
 * reaches `CitationLink` below — the component was never broken, the
 * input it received already had the citation stripped out. Allowlist
 * `citation:` explicitly; defer to `defaultUrlTransform` for everything
 * else so real links keep the same sanitization they'd otherwise get.
 */
import React from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Anchor } from "@mantine/core";
import type { DocumentChatCitation } from "@/domain/documentChat";
import { docxHelper } from "@/commands/docxHelper";

const CITATION_HREF_RE = /^citation:(\d+)$/;

function urlTransform(url: string): string {
  return CITATION_HREF_RE.test(url) ? url : defaultUrlTransform(url);
}

function onCitationClick(citation: DocumentChatCitation): void {
  void docxHelper.scrollToParagraph(citation.paragraphId, citation.quote);
}

type MarkdownAnchorProps = {
  href?: string;
  children?: React.ReactNode;
};

function makeCitationLink(citations: DocumentChatCitation[]) {
  return function CitationLink({ href, children }: MarkdownAnchorProps) {
    const match = href ? CITATION_HREF_RE.exec(href) : null;
    if (!match) return <a href={href}>{children}</a>;

    const citation = citations[Number(match[1])];
    // Index out of range (model miscounted) — degrade to plain text
    // rather than a dead/misleading link.
    if (!citation) return <>{children}</>;

    return (
      <Anchor
        href="#"
        c="indigo"
        onClick={(e: React.MouseEvent) => {
          e.preventDefault();
          onCitationClick(citation);
        }}
      >
        {children}
      </Anchor>
    );
  };
}

export type MarkdownContentProps = {
  content: string;
  citations?: DocumentChatCitation[];
};

export const MarkdownContent: React.FC<MarkdownContentProps> = ({ content, citations = [] }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={urlTransform}
      components={{ a: makeCitationLink(citations) }}
    >
      {content}
    </ReactMarkdown>
  );
};
