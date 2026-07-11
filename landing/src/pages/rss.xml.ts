// Q2-15 — RSS 2.0 feed for the SPA blog. Generated at build time from the SINGLE post source
// (src/lib/blog_posts.json) so it can never diverge from /blog. Cheapest discoverability multiplier:
// feed readers + AI answer engines (robots.txt already welcomes GPTBot/ClaudeBot/PerplexityBot) get a
// machine-readable changelog. Static output (Astro endpoint) — no server, honest last-build snapshot.
import posts from '../lib/blog_posts.json';

const SITE = 'https://earn-defi.com';

function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export async function GET() {
  const sorted = [...posts].sort((a, b) => (a.date < b.date ? 1 : -1)); // newest first
  const items = sorted
    .map((p) => {
      const url = `${SITE}/blog/${p.slug}`;
      // RFC-822 date at 00:00:00 GMT for the post's calendar day (build-time, deterministic).
      const pubDate = new Date(`${p.date}T00:00:00Z`).toUTCString();
      return [
        '    <item>',
        `      <title>${esc(p.title)}</title>`,
        `      <link>${url}</link>`,
        `      <guid isPermaLink="true">${url}</guid>`,
        `      <pubDate>${pubDate}</pubDate>`,
        `      <category>${esc(p.tag)}</category>`,
        `      <description>${esc(p.summary)}</description>`,
        '    </item>',
      ].join('\n');
    })
    .join('\n');

  const xml = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
    '  <channel>',
    '    <title>SPA — earn-defi.com</title>',
    `    <link>${SITE}/blog</link>`,
    `    <atom:link href="${SITE}/rss.xml" rel="self" type="application/rss+xml" />`,
    '    <description>Updates, milestones, and engineering changelog for SPA — systematic onchain stablecoin yield.</description>',
    '    <language>en</language>',
    items,
    '  </channel>',
    '</rss>',
    '',
  ].join('\n');

  return new Response(xml, {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' },
  });
}
