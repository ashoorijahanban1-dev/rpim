# ADR 0040 — Frontend standard: 21st.dev interop layer + Framer Motion (pre-M22 polish)

**Status:** accepted (2026-07-20)

## Context

The dashboard's look is a hand-rolled CSS design-token system (porcelain/
gold, Vazirmatn, RTL — globals.css is the source of truth) with zero
Tailwind. The Product Owner adopted the 21st.dev component standard and
Framer Motion for a premium-SaaS feel. Dropping full Tailwind (with
preflight) onto the existing system would reset its base styles and
visually break every page.

## Decisions

- **Tailwind v4, utilities-only, NO preflight.** globals.css imports only
  `tailwindcss/theme.css` + `tailwindcss/utilities.css` into explicit
  layers; the existing token system keeps owning base styles. Utility
  classes become available additively — exactly what drop-in 21st.dev/
  shadcn components need to style themselves.
- **The v4-native "tailwind config" is the `@theme` block** (no JS config
  file in v4): the Pro UI scale — radius tokens (card/panel/pill), a
  smooth 3-step shadow scale (soft/float/pop), a decelerating ease and a
  `fade-up` animation token — plus `@theme inline` mapping brand colors
  (`--color-gold: var(--gold)`, …) so generated utilities inherit the
  RPIM palette in both light and dark.
- **`cn` in `lib/utils.ts`** (clsx + tailwind-merge), the ecosystem-
  standard import path (`@/lib/utils`) every 21st.dev component expects;
  `lucide-react` is the icon set (SVG icons, never emoji — UX guideline).
- **Motion standard:** framer-motion with the entrance pattern
  `initial={{opacity:0, y:20}} → animate={{opacity:1, y:0}}`, 300ms,
  ease `[0.22, 1, 0.36, 1]`, parent-level `staggerChildren` ≈ 80ms — and
  **every animated tree sits under `<MotionConfig reducedMotion="user">`**
  so prefers-reduced-motion users get no gratuitous movement
  (accessibility is priority 1 in the design rulebook). First applied
  surface: the Super Admin page load stagger.
- **21st.dev connector** rides `.mcp.json` (remote MCP, OAuth — PR #72);
  the vendored `ui-ux-pro-max` skill supplies the design rulebook that
  reviews any new UI against styles/palettes/UX guidelines.

## Consequences

- New pages/components may freely mix existing token classes with
  Tailwind utilities; 21st.dev components paste in with at most palette
  tweaks via the mapped color tokens.
- ruff/pytest untouched; the dashboard CI job (tsc + eslint + next build)
  covers the new PostCSS pipeline.
- Persian stays locale-only (unchanged rule); RTL is unaffected because
  preflight is excluded.
