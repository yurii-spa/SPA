#!/bin/bash
# RETIRED 2026-06-27. LLM_FORBIDDEN. stdlib only.
#
# This used to copy the standalone root index.html dashboard into
# landing/public/app.html so Cloudflare Pages served it at earn-defi.com/app.
# That self-contained 756KB blob is gone: the canonical dashboard is now a
# first-class Astro page — landing/src/pages/dashboard.astro — rendered inside
# <Layout> (canonical chrome + Console design tokens) with a real-time React
# island (landing/src/components/DashboardLive.jsx) polling api.earn-defi.com.
#
# There is nothing to sync. /app 301-redirects to /dashboard (landing/public/_redirects).
# Do NOT re-introduce app.html — it re-fragments the site.
echo "sync_dashboard_to_landing.sh is RETIRED — the dashboard is now landing/src/pages/dashboard.astro (no blob to sync)." >&2
exit 0
