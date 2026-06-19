import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwind from '@astrojs/tailwind';

// https://astro.build/config
export default defineConfig({
  site: 'https://earn-defi.com',
  output: 'static',
  integrations: [
    react(),
    tailwind(),
    // sitemap() removed — @astrojs/sitemap@3.2.x crashes with undefined.reduce() bug.
    // Re-add after updating to 3.4+.
  ],
  // Cloudflare Pages: build output goes to ./dist
  // Build command: npm run build
  // Build output directory: dist
  // Node version: 20
    // CF Pages rebuild trigger: v9.20 2026-06-19
});
