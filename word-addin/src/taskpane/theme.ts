/**
 * Mantine theme for the Word add-in task pane.
 *
 * Colors mirror the web app's Practice palette
 * (web/src/lib/lq-ai/styles/practice.css) so the add-in's chat surface
 * reads as the same product as the `/lq-ai/*` web shell, not a bolt-on.
 * Sage is the primary/secure tone; slate is the privilege/tier tone;
 * amber is warning/override; red is error/audit-unhealthy — same four
 * tones TrustPill.svelte uses on the web side.
 */
import { createTheme, rem, type MantineColorsTuple } from "@mantine/core";

const sage: MantineColorsTuple = [
  "#effbf9",
  "#e0f4f0",
  "#bbe9e1",
  "#93ddd0",
  "#73d4c2",
  "#60ceba",
  "#54cbb5",
  "#45b39f",
  "#38a08d",
  "#1f7a6b",
];

const slate: MantineColorsTuple = [
  "#eef2f7",
  "#dde6ef",
  "#bccde3",
  "#96b1d2",
  "#7797c2",
  "#6486b7",
  "#587cb0",
  "#496a9c",
  "#3d5c8a",
  "#355a82",
];

const amber: MantineColorsTuple = [
  "#fdf6ea",
  "#fbebce",
  "#f6d69c",
  "#efbd66",
  "#eaa93a",
  "#e59d1e",
  "#e29711",
  "#c98107",
  "#a1670c",
  "#a16e1f",
];

export const theme = createTheme({
  primaryColor: "sage",
  colors: { sage, slate, amber },
  //fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif",
  fontSizes: {
    xs: rem(14),
    sm: rem(16),
    md: rem(18),
    lg: rem(19),
    xl: rem(20),
  },
  headings: {
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif",
    fontWeight: "700",
    sizes: {
      h1: { fontWeight: "700", fontSize: rem(30), lineHeight: "1.4" },
      h2: { fontWeight: "700", fontSize: rem(18), lineHeight: "1.25" },
      h3: { fontWeight: "700", fontSize: rem(16), lineHeight: "1.1" },
    },
  },
  defaultRadius: "md",
  shadows: {
    xs: "0 1px 2px rgba(0, 0, 0, 0.44)",
    sm: "0 2px 4px rgba(0, 0, 0, 0.48)",
    md: "0 4px 10px rgba(0, 0, 0, 0.42)",
    lg: "0 8px 18px rgba(0, 0, 0, 0.56)",
    xl: "0 12px 28px rgba(0, 0, 0, 0.60)",
  },

  components: {
    InputWrapper: {
      styles: {
        label: {
          lineHeight: "1.0",
          marginBottom: rem(0),
          fontSize: rem(12),
          color: "var(--mantine-color-gray-7)",
        },
      },
    },
    Select: {
      styles: {
        dropdown: { boxShadow: "var(--mantine-shadow-md)" },
      },
    },
  },
});
