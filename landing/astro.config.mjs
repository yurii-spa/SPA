import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://earn-defi.com',
  output: 'static',
  integrations: [
    react(),
    tailwind(),
    sitemap(),
  ],
  // Cloudflare Pages: build output goes to ./dist
  // Build command: npm run build
  // Build output directory: dist
  // Node version: 20
});
