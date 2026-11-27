/**
 * TrustPill — small ambient-trust indicator, ported from the web app's
 * TrustPill.svelte (web/src/lib/lq-ai/components/TrustPill.svelte) so the
 * add-in's chat surface uses the same tone contract: variant picks a
 * default tone (secure/provider/audit → sage, tier → slate, warn → amber,
 * error → red); `tone` overrides it. `display="dot"` renders a bare dot
 * for the personalization-toggle-collapsed state.
 */
import React from "react";
import { Badge, type MantineColor } from "@mantine/core";

export type TrustVariant = "secure" | "tier" | "provider" | "audit" | "warn" | "error";
export type TrustTone = "sage" | "slate" | "amber" | "red" | "neutral";
export type TrustDisplay = "label" | "dot";

const VARIANT_DEFAULT_TONE: Record<TrustVariant, TrustTone> = {
  secure: "sage",
  tier: "slate",
  provider: "sage",
  audit: "sage",
  warn: "amber",
  error: "red",
};

const TONE_COLOR: Record<TrustTone, MantineColor> = {
  sage: "sage",
  slate: "slate",
  amber: "amber",
  red: "red",
  neutral: "gray",
};

export function toneFor(variant: TrustVariant, override: TrustTone | undefined): TrustTone {
  return override ?? VARIANT_DEFAULT_TONE[variant] ?? "neutral";
}

type TrustPillProps = {
  variant: TrustVariant;
  label: string;
  tone?: TrustTone;
  display?: TrustDisplay;
  onClick?: () => void;
};

export const TrustPill: React.FC<TrustPillProps> = ({
  variant,
  label,
  tone,
  display = "label",
  onClick,
}) => {
  const resolvedTone = toneFor(variant, tone);
  return (
    <Badge
      variant="light"
      color={TONE_COLOR[resolvedTone]}
      radius="xl"
      size={display === "dot" ? "xs" : "sm"}
      aria-label={label}
      onClick={onClick}
      style={{
        cursor: onClick ? "pointer" : "default",
        textTransform: "none",
      }}
    >
      {display === "dot" ? "●" : label}
    </Badge>
  );
};
