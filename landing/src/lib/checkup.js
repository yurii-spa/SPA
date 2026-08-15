/**
 * checkup.js — ONE switch for every public link that points at checkup.earn-defi.com.
 *
 * Why this file exists (cycle #228, 2026-08-14): the WHOLE subdomain
 * checkup.earn-defi.com returns 404 on every route (`/`, `/check`, `/sample-report`),
 * while the landing kept shipping live public CTAs into it. Visitors hit a hard 404 and
 * the cloud watchdog `site-freshness` (which runs scripts/funnel_link_check.py) went red
 * on EVERY run — so a red job stopped being a signal at all.
 *
 * The checkup service is NOT in this repo: it is `yurii-spa/defi-checkup` (private,
 * Railway) — see docs/CHECKUP_NOTIFICATIONS_SPEC.md. Nothing in this repo can bring it
 * back; all this repo can honestly do is stop promising a page that does not exist.
 *
 * Flip CHECKUP_ENABLED back to `true` in ONE place the moment
 * `curl -L https://checkup.earn-defi.com/check` answers 2xx again — every CTA, the hero
 * widget, the nav group and the funnel checker read this flag (the Python checker parses
 * this very file, so the site and the watchdog cannot drift apart).
 *
 * NOTE: this file carries NO yield numbers, NO tier names, NO legal copy — links only.
 */

export const CHECKUP_ORIGIN = 'https://checkup.earn-defi.com';

/** false ⇒ the subdomain is down; do not render any link into it. */
export const CHECKUP_ENABLED = false;

/** Build a checkup URL (path must start with "/"). */
export function checkupUrl(path = '/check', query = '') {
  return CHECKUP_ORIGIN + path + (query ? (query.startsWith('?') ? query : '?' + query) : '');
}
