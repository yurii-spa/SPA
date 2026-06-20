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
  build: {
    // Assets go into _assets/ (clean separation from pages)
    assets: '_assets',
    // Inline small stylesheets to reduce round-trips
    inlineStylesheets: 'auto',
  },
  vite: {
    build: {
      // Minify with esbuild (default, fast)
      minify: 'esbuild',
      rollupOptions: {
        output: {
          // Single chunk per page — optimal for static sites with no shared JS state
          manualChunks: undefined,
        },
      },
    },
    // Optimize deps on first load
    optimizeDeps: {
      include: ['react', 'react-dom'],
    },
  },
  // Cloudflare Pages: build output goes to ./dist
  // Build command: npm run build
  // Build output directory: dist
  // Node version: 20
});
