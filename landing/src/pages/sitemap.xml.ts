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
// console (robots Disallow), and error pages — none of which belong in a public sitemap.
const PAGE_GLOB = import.meta.glob('./**/*.astro');

function routesFromGlob(): string[] {
  const out: string[] = [];
  for (const key of Object.keys(PAGE_GLOB)) {
    const rel = key.replace(/^\.\//, '').replace(/\.astro$/, ''); // 'blog/2026-..' | 'index' | 'admin/index'
    if (rel.includes('[')) continue; // dynamic template, expanded explicitly below
    if (rel === 'admin' || rel.startsWith('admin/')) continue; // robots Disallow: /admin
    if (rel === '404' || rel === '500') continue;
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

  const urls = [...routes]
    .sort()
    .map((path) => `  <url><loc>${SITE}${path === '/' ? '/' : path}</loc></url>`)
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
