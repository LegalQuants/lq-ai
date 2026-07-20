/**
 * ProvenancePill — pill attached to AI messages, ported from the web app's
 * ProvenancePill.svelte (web/src/lib/lq-ai/components/ProvenancePill.svelte).
 * See docs/superpowers/specs/2026-05-10-m1-frontend-design.md §5.2.
 */
import React from "react";
import { TrustPill } from "@/components/chat/TrustPill";

export type ProvenanceKind =
  "skill" | "tier" | "provider" | "kb" | "audit" | "enhanced" | "caselaw";

const KIND_ICON: Record<ProvenanceKind, string> = {
  skill: "🛠️",
  tier: "🔒",
  provider: "🧠",
  kb: "📎",
  audit: "📜",
  enhanced: "✨",
  caselaw: "⚖",
};

const KIND_DESCRIPTION: Record<ProvenanceKind, string> = {
  skill:
    "Skill — this answer was shaped by a reusable structured prompt. Click to read the skill source.",
  tier: "Inference tier — where this answer was processed (Tier 1 = local, Tier 5 = consumer). Click for details.",
  provider: "AI provider — which model produced this answer. Click for details.",
  kb: "Knowledge base — documents the AI could search and cite from for this answer. Click to view.",
  audit: "Audit log — this action was recorded for compliance and review. Click to view the entry.",
  enhanced:
    "Enhanced Prompt — the AI rewrote your short prompt into a structured legal prompt before answering. Click to compare.",
  caselaw:
    "Case law — this answer drew on external legal sources (e.g. CourtListener). Click to view sources consulted.",
};

export type ProvenanceTone = "sage" | "slate" | "amber";

export function toneFor(kind: ProvenanceKind, tierMismatch: boolean): ProvenanceTone {
  if (kind === "tier") return tierMismatch ? "amber" : "slate";
  if (kind === "caselaw") return "slate";
  return "sage";
}

type ProvenancePillProps = {
  kind: ProvenanceKind;
  summary: string;
  tierMismatch?: boolean;
  onTap?: () => void;
};

export const ProvenancePill: React.FC<ProvenancePillProps> = ({
  kind,
  summary,
  tierMismatch = false,
  onTap,
}) => {
  const tone = toneFor(kind, tierMismatch);
  return (
    <span title={KIND_DESCRIPTION[kind]}>
      <TrustPill
        variant="audit"
        tone={tone}
        label={`${KIND_ICON[kind]} ${summary}`}
        onClick={onTap}
      />
    </span>
  );
};
