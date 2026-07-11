// sitemap.xml — the URL index for crawlers + AI answer engines. robots.txt points here
// (`Sitemap: https://earn-defi.com/sitemap.xml`), but @astrojs/sitemap was removed (a 3.2.x
// undefined.reduce() crash) so the reference was DANGLING → a 404 for every crawler that
// followed it. This static endpoint regenerates it deterministically at build time from the
// REAL page set (import.meta.glob — never a hand-maintained list that drifts) so it can't go
// stale against /blog, /protocols, or new pages. Static output, no server.
import protocolVerdicts from '../lib/protocol_verdicts.json';

export const prerender = true;

const SITE = 'https://earn-defi.com';

// Every .astro page in this tree. Excludes: dynamic templates ([slug]), the /admin operator
// console (robots Disallow), error pages, and INTERNAL pages (noindex dev showcases) — none of
// which belong in a public sitemap.
const PAGE_GLOB = import.meta.glob('./**/*.astro');

// Public-URL pages that are noindex (dev/internal showcases) — keep them out of the sitemap so a
// crawler is never pointed at operator internals. Mirror any page that passes noindex to Layout.
const INTERNAL_ROUTES = new Set<string>(['cockpit-kit']);

function routesFromGlob(): string[] {
  const out: string[] = [];
  for (const key of Object.keys(PAGE_GLOB)) {
    const rel = key.replace(/^\.\//, '').replace(/\.astro$/, ''); // 'blog/2026-..' | 'index' | 'admin/index'
    if (rel.includes('[')) continue; // dynamic template, expanded explicitly below
    if (rel === 'admin' || rel.startsWith('admin/')) continue; // robots Disallow: /admin
    if (rel === '404' || rel === '500') continue;
    if (INTERNAL_ROUTES.has(rel)) continue; // noindex internal/dev showcase
    const path = rel === 'index' ? '/' : rel.endsWith('/index') ? `/${rel.slice(0, -6)}` : `/${rel}`;
    out.push(path);
  }
  return out;
}

export async function GET() {
  const routes = new Set<string>(routesFromGlob());
  // Expand the dynamic /protocols/[slug] template from its real data source.
  for (const p of (protocolVerdicts as { protocols: { slug: string }[] }).protocols) {
    routes.add(`/protocols/${p.slug}`);
  }
  routes.add('/rss.xml'); // the feed is a real, linkable resource

  // The site is built with Astro's directory format: the CANONICAL 200 URL carries a trailing
  // slash (`/fundability/`), and the no-slash form 308-redirects to it. List the canonical form
  // so every sitemap entry is a 200, not a redirect (crawlers penalise redirect-only sitemaps).
  // Real files (.xml) and the root stay as-is.
  const canonical = (p: string): string => {
    if (p === '/' || p.endsWith('.xml') || p.endsWith('/')) return p;
    return `${p}/`;
  };

  const urls = [...routes]
    .map(canonical)
    .sort()
    .map((path) => `  <url><loc>${SITE}${path}</loc></url>`)
    .join('\n');

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    urls,
    '</urlset>',
    '',
  ].join('\n');

  return new Response(xml, {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' },
  });
}
