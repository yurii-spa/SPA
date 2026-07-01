/*
 * ui/index.js — barrel re-export for the shared Astro UI kit (V2 §3.4).
 * Import in .astro: `import { Badge, Card, PageHeader } from '../components/ui';`
 * (React islands import from ./kit.jsx and ./tokens.js instead.)
 */
export { default as Badge } from './Badge.astro';
export { default as StatusPill } from './StatusPill.astro';
export { default as Card } from './Card.astro';
export { default as Button } from './Button.astro';
export { default as LiveChip } from './LiveChip.astro';
export { default as Eyebrow } from './Eyebrow.astro';
export { default as PageHeader } from './PageHeader.astro';
export { default as Section } from './Section.astro';
export { default as Table } from './Table.astro';
export { default as Th } from './Th.astro';
export { default as Td } from './Td.astro';
