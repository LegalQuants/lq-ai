/**
 * Deep-link card.
 *
 * Per Decision B-4 in the Phase B prep doc, each empty tab renders this
 * card explaining why the in-Word feature surface is not yet shipped and
 * offering a button that opens the equivalent web-app surface in a new
 * browser tab. The card body is the contract surface for a community
 * contributor: when DE-287 work lands a real implementation, this card
 * is the file that gets replaced with the actual tab content.
 */
import React from "react";

type DeepLinkCardProps = {
  title: string;
  body: string;
  href: string;
};

export const DeepLinkCard: React.FC<DeepLinkCardProps> = ({
  title,
  body,
  href,
}) => {
  return (
    <section
      className="lq-card"
      role="tabpanel"
      aria-labelledby={`lq-tab-active`}
    >
      <h2 className="lq-card-title">{title}</h2>
      <p className="lq-card-body">{body}</p>
      <a
        className="lq-card-cta"
        href={href}
        target="_blank"
        rel="noopener noreferrer"
      >
        Open in LQ.AI web app
        <span aria-hidden="true" style={{ marginLeft: "0.4em" }}>
          →
        </span>
      </a>
    </section>
  );
};
