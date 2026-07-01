/** @type {import('tailwindcss').Config} */
// Unified design tokens — docs/SITE_DESIGN_SYSTEM.md §3 (single source of truth).
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        // Backgrounds — ONE near-black scale (kills the 5 competing blacks)
        bg: {
          base: '#0A0C10',
          surface: '#11141A',
          'surface-2': '#181C24',
          elevated: '#1E232C',
        },
        border: {
          DEFAULT: '#232934',
          strong: '#313945',
        },
        // Text scale
        text: {
          primary: '#E8EAF0',
          secondary: '#A6ADBB',
          muted: '#6B7280',
          faint: '#444B57',
        },
        // Brand accent — refined indigo-blue (single primary)
        accent: {
          DEFAULT: '#5B8DEF',
          hover: '#79A4F5',
          dim: '#2C4A8A',
          // numeric scale kept for legacy `accent-400/500` usages, retoned to indigo
          50: '#eef3fd',
          100: '#dbe6fb',
          200: '#b7ccf6',
          300: '#93b3f2',
          400: '#79A4F5',
          500: '#5B8DEF',
          600: '#3f6fd6',
          700: '#2C4A8A',
          800: '#24407a',
          900: '#1c3360',
        },
        // Secondary accent — quant teal (data viz, live ticks)
        'data-teal': '#36C2B4',
        teal: {
          400: '#36C2B4',
          500: '#2aa99c',
          600: '#1f8479',
        },
        // Semantic — meaning only (never decoration / eyebrow)
        // Canonical risk-color language (docs/SITE_DESIGN_SYSTEM_V2.md §3.3 — ONE map):
        //   SAFE/ENTRY/PASS/live = ok(green) · WATCH/PENDING = warn(amber) ·
        //   REFUSE/FAIL/kill/offline = danger(coral) · UNKNOWN = text-muted.
        //   A/B/C/D risk tiers = data-teal / accent / warn / danger (severity ramp).
        ok: '#34D399',
        warn: '#F2B53C',
        danger: '#F26D6D',
        info: '#5B8DEF',
        // Semantic tint/border tokens (V2 §3.3 — tokenize the ~20× rgba literals once).
        // Consumed via bg-ok-bg / border-ok-border etc, or via the shared StatusPill.
        'ok-bg': 'rgba(52,211,153,0.10)',
        'ok-border': 'rgba(52,211,153,0.30)',
        'warn-bg': 'rgba(242,181,60,0.10)',
        'warn-border': 'rgba(242,181,60,0.30)',
        'danger-bg': 'rgba(242,109,109,0.12)',
        'danger-border': 'rgba(242,109,109,0.35)',
        'accent-bg': 'rgba(91,141,239,0.10)',
        'accent-border': 'rgba(91,141,239,0.30)',
        'teal-bg': 'rgba(54,194,180,0.12)',
        'teal-border': 'rgba(54,194,180,0.30)',
        // Legacy surface aliases mapped onto the unified scale
        surface: {
          900: '#0A0C10',
          800: '#11141A',
          700: '#181C24',
          600: '#1E232C',
          500: '#232934',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '16px',
        xl: '24px',
      },
      boxShadow: {
        sm: '0 1px 2px rgba(0,0,0,.4)',
        md: '0 4px 16px rgba(0,0,0,.45)',
        cta: '0 6px 20px rgba(91,141,239,.25)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
