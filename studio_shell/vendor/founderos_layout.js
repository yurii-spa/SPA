// ── COPY + ADAPT from FounderOS (MIT) — presentation/layout math ─────────────────────
// Source: github.com/Bennettxai/FounderOS-DEMO @ ad46d772744ce93e898a203526e2a2967e583205
//   lib/tree-layout.ts  → round2, RING_FRAC, SECTOR_FILL, responsiveRingR, radialRestLayout, edgeArc, branchWidth
//   components/KnowledgeGraph.tsx → hexPts (hexagonal node points), CAT tier radii
// License: MIT (© 2026 FounderOS). Ported TypeScript → ESM JavaScript verbatim in behaviour;
// the ONLY modification is TS type stripping + exposing a generic `pillars` shape. This is the
// real FounderOS visual system (concentric density-weighted rings · hex nodes · bowed edges),
// reused so Earn DeFi inherits its look — not a from-scratch lookalike.

export const round2 = (n) => { const v = Math.round(n * 100) / 100; return Object.is(v, -0) ? 0 : v; };

// ring radii as fractions of min(width,height) — FounderOS lib/tree-layout.ts
export const RING_FRAC = [0, 105 / 600, 152 / 600, 200 / 600, 248 / 600];
const SECTOR_FILL = 0.84;

export function responsiveRingR(width, height) {
  const m = Math.max(1, Math.min(width, height));
  return RING_FRAC.map((f) => round2(f * m));
}

// FounderOS radialRestLayout: self at centre; each pillar on ring[1] with a
// density-weighted angular sector; its task/worker/tool children fan on ring[2..4].
export function radialRestLayout({ selfId, pillars, cx, cy, width = 880, height = 600, ringR, startAngle = -Math.PI / 2 }) {
  ringR = ringR || responsiveRingR(width, height);
  const positions = new Map();
  const polar = (r, a) => ({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
  positions.set(selfId, { x: cx, y: cy });
  const n = Math.max(1, pillars.length);
  const weights = pillars.map((p) => Math.max(1, (p.taskIds?.length || 0) + (p.workerIds?.length || 0) + (p.toolIds?.length || 0)));
  const total = weights.reduce((s, w) => s + w, 0) || 1;
  const spans = weights.map((w) => (w / total) * Math.PI * 2);
  const centersRaw = []; let cum = 0;
  for (let i = 0; i < n; i++) { centersRaw[i] = cum + spans[i] / 2; cum += spans[i]; }
  const offset = startAngle - (centersRaw[0] ?? 0);
  pillars.forEach((p, i) => {
    const center = centersRaw[i] + offset;
    positions.set(p.teamId, polar(ringR[1], center));
    if (p.headId) positions.set(p.headId, polar((ringR[1] + ringR[2]) / 2, center));
    const half = (spans[i] / 2) * SECTOR_FILL;
    const ring = (ids, r) => { const k = (ids || []).length; (ids || []).forEach((id, j) => { const t = k <= 1 ? 0 : (j / (k - 1)) * 2 - 1; positions.set(id, polar(r, center + t * half)); }); };
    ring(p.taskIds, ringR[2]); ring(p.workerIds, ringR[3]); ring(p.toolIds, ringR[4]);
  });
  return positions;
}

// hexagonal node points (flat radius r), first vertex at -90° — KnowledgeGraph.tsx
const HEX_CACHE = new Map();
export function hexPts(r) {
  const key = Math.round(r * 100); let s = HEX_CACHE.get(key);
  if (!s) { s = Array.from({ length: 6 }, (_, k) => { const a = (k * Math.PI) / 3 - Math.PI / 2; return `${(r * Math.cos(a)).toFixed(3)},${(r * Math.sin(a)).toFixed(3)}`; }).join(' '); HEX_CACHE.set(key, s); }
  return s;
}

// gentle perpendicular-bowed quadratic arc between two points — the "living web" swirl
export function edgeArc(a, b, bow = 0.12) {
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, off = bow * len;
  const cx = mx + (-dy / len) * off, cy = my + (dx / len) * off;
  return `M ${round2(a.x)} ${round2(a.y)} Q ${round2(cx)} ${round2(cy)}, ${round2(b.x)} ${round2(b.y)}`;
}

export function branchWidth(depth) { return round2(Math.max(1, 3.6 - depth * 0.8)); }
