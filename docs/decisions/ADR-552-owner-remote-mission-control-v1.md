# ADR-552 · Owner Remote / Mission Control v1

- **Status:** ACCEPTED (owner macro-epic 2026-10-03 «OWNER REMOTE / MISSION CONTROL v1»)
- **Date:** 2026-10-03
- **Related:** ADR-469 / ADR-492 / ADR-493 (Director OS, Studio Shell, voice seams), ADR-521 (Telegram Owner
  Control Plane), ADR-527 (memory), ADR-533 / ADR-537 (package status, «colour is not a risk grade»),
  ADR-551 (build loop, provenance, resource guard, redaction).
- **Boundary:** read-only. No money, risk, strategy, publication or deployment action. Real capital = 0.

## Phase 0 — what already existed (audit 2026-10-03)

| Surface | Verdict | Fact |
|---|---|---|
| Director report (`director_report.collect`) | IMPLEMENTED — the canonical owner read model | Telegram `/report`. Newest and richest; reads agent health, resources, packages, trading, orphans |
| Director OS web cockpit (`scripts/cartographer/*`, `com.spa.director_server` :8788) | IMPLEMENTED (desktop, loopback) / its projection DUPLICATES the Director | Hardened server (GET only, fixed routes, CSP, in-memory atomic bundle). RU only; `last_successful_publish` frozen since 09-20 |
| Telegram Owner Control Plane (Bridge bot + SPA bot) | IMPLEMENTED — today's real mobile remote | Owner answers via the SPA bot buttons (`record_owner_answer`, double owner check). Confirm-first text/voice intake via the Bridge bot → `spa_core.owner_remote` |
| `studio_shell/` (Mission Control + Studio View prototype) | PARTIAL — design reference | Mobile-first, RU/EN, not deployed. ADR-521 found it answered GREEN from an empty projection |
| landing `/admin/*` | PARTIAL / STALE | Behind Cloudflare Access; `cmo-drafts` approve is broken (401) |
| Public `/dashboard`, `/system`, `/cockpit*` | IMPLEMENTED product | Not an owner surface (ADR-492) |
| SPA API (:8765 via tunnel `api.earn-defi.com`, no Access) | public | **Found and fixed during this audit:** `/api/live/data/{file}` served every `data/*.json` publicly, including `resource_health.json`, which held the tunnel token for ~20 min. Closed by `ecd14c84` with an allow-list |

Nothing owner-private is reachable from the phone today except Telegram.

## WP-A01 — information architecture

Five top-level areas, the same on phone and desktop. The phone shows the compact form; the desktop shows
detail and drill-downs. **Studio OS** (tasks, agents, evidence, releases, system) and **SPA / Capital**
(strategies, positions, research) are separate areas and are labelled so in the UI.

| Area | Contents |
|---|---|
| OVERVIEW | System state + critical alerts · NEEDS YOU (owner decisions) · NOW (current epic, work in progress, workers, heavy jobs) · CAPITAL (3 paper portfolios + Trading Research, real capital 0) · TODAY (releases, incidents) · resources |
| CAPITAL | Conservative · Balanced · Aggressive (package status: work / data / decision / evidence / live admission) · Trading Research · real-capital box. No cash/treasury view: there is no canonical source yet |
| STUDIO | Epics (ROADMAP) · board (in progress, blocked, queued, recently done) · lineage drill-down (IDEA→…→MEMORY, ADR-551) · agents · orphans · workers |
| DECISIONS | Pending owner decisions (reason, requested action, risk class, created, source, evidence, affected artifacts, scope, Telegram link) · recently resolved |
| SYSTEM | Resources (disk, memory pressure, swap, process classes, heavy jobs) · cleanup · backups · code identity · services · agents · incidents · kill-switch state |

## WP-A02 — read-model contract

ONE read model: `spa_core/studio_os/mission_control.py` → `mission.json` (`schema: mission-control/1`).
It composes `director_report.collect` (the projection Telegram already shows), `package_status.public_view`,
`build_loop.board/lineage`, the origin tracker overlaid with production-tree owner answers, git history and
the guard's files. **The UI reads only this file.** `CONTRACT` in the module names, for every section:
canonical source · `stale_after_min` · UNKNOWN behaviour · redaction · mobile · may-alert.
`test_mission_control_contract.py` enforces that every emitted section is declared.

Each section carries `_meta = {state, colour, sources, observed_at, age_min, stale_after_min, reason}`.
A missing source gives `NOT_MEASURED` with a reason. An observation older than its contract gives `STALE`.
Neither is ever `HEALTHY`, `0` or `[]`.

**Shared semantics fixed in the Director as well** (one meaning in Telegram and Mission Control):
- the kill switch is read from `kill_switch_status.json` + `derisk_status.json` + the manual flag, not the flag alone;
- an unmeasured disk raises «не измерено»;
- heavy-job leases are read without pruning;
- processes are shown by NAME only;
- an evidence chain of `None` is «не измерено», not «НАРУШЕНА»;
- the owner queue = origin cards + production-tree answers (743 vs 1,182 cards measured between the trees).

## WP-A03 — status vocabulary

- Operational: RUNNING / PAUSED / FAILED / UNKNOWN
- Health: HEALTHY / DEGRADED / STALE / NOT_MEASURED / CRITICAL
- Work: QUEUED / IN_PROGRESS / BLOCKED / REVIEW / DONE
- Decision: NEEDS_OWNER / ACCEPTED / ANSWERED / INGESTED / REJECTED / EXPIRED / UNKNOWN
- Capital mode: PAPER / SHADOW / LIVE_NOT_APPROVED
- Evidence: WARMUP / ACCUMULATING / REPORTABLE

**Colour follows HEALTH only** — never profit, risk or approval for real money (ADR-537). Real capital is
always `LIVE_NOT_APPROVED` and is shown with the basis it was read from (`execution_mode`, engine-reported
`live_capital_usd`); unreadable ⇒ `UNKNOWN`, never a default 0. The card lifecycle has no REVIEW status:
review evidence is a lineage stage, and the UI says so instead of inventing a REVIEW column.

## WP-A04 — owner action boundary (v1)

The web UI **writes nothing**. Allowed:
- open any section, card, lineage or release detail;
- **answer a decision** → a deep link `t.me/SPA_Monitor_bot?start=od_<card>` opens THAT card with its
  buttons in the SPA bot. The bot handles the link (new: `TelegramBot._handle_decision_deeplink`, owner-gated,
  exact-slug match), and the answer goes through the existing canonical writer `record_owner_answer`.
  No second decision path; no web identity pretending to be the owner (invariant #14, ADR-186);
- **Ask / Idea / Voice / Report** → the Bridge bot (confirm-first intake, local Whisper, ADR-521).

Forbidden: start/stop service, kill switch, delete, publish, deploy, strategy, money, risk, Bridge gates,
alert action buttons, CMO approve. The SPA API on :8765 is public and gets NO owner routes.

## Serving and phone exposure

- `spa_core/studio_os/mission_server.py` uses the Director server's design: 127.0.0.1 only, GET/HEAD, a
  fixed route map (no path translation), the bundle held in memory and swapped atomically, strict CSP, no-store.
- A builder agent (`com.spa.mission_control`, every 5 min) writes a new bundle and moves the pointer.
- **Phone access needs a path that does not exist yet.** No tunnel route, no Cloudflare Access app, no
  Tailscale. Enabling it is an owner action in Cloudflare (subject №3: external exposure; the agent holds no
  Cloudflare API credential) — see the consolidated owner gate.
- **Two listeners, never one (WP-A05 finding 1).** cloudflared connects from 127.0.0.1 and may rewrite `Host`
  to `localhost`, so a «loopback Host needs no JWT» rule on a tunnelled port is a bypass. The LOCAL listener
  (127.0.0.1:8790) serves only loopback Hosts and refuses any request carrying a proxy/Cloudflare header. The
  PUBLIC listener exists only when `~/studio-os-serve/mission_access.json` (mode 0600, outside the public repo:
  owner e-mails are not published) names the public host, AUD, team and owner e-mails; it is a separate
  loopback port (default 8792, the only port a tunnel may point at) and requires a valid Access JWT (RS256,
  AUD, issuer, owner e-mail) AND the public Host on EVERY route, `/healthz` included. Certs are cached in
  memory; refusals close the connection; request bodies are refused (no keep-alive smuggling).

## Architecture freeze gate

- IA fixed above.
- Contract deterministic, with a test-enforced source for every section.
- Source-of-truth mapping complete (audit tables, in the journal).
- Redaction: `safe_text` (secrets via `redact_cmd`, paths, e-mails, ids ≥ 8 digits), process names only,
  and `public_view` scrub for packages.
- Mobile and desktop scope as in WP-A01.
- No new state store: the model is regenerated from canonical sources every 5 minutes; deleting
  `mission.json` loses nothing.

## WP-A05 — independent review (2026-10-03) and remediation

Sixteen points; every valid one fixed before delivery, each with a test that fails without the fix:

| # | Finding | Fix |
|---|---|---|
| 1 | loopback-Host exemption bypasses Access behind a tunnel | two listeners (above) |
| 2 | keep-alive desync after a refusal | close on every non-2xx; bodies refused |
| 3 | certs fetched per request, cache in world-writable `/tmp` | in-memory TTL cache; disk cache 0600 under `~/studio-os-serve`; any error ⇒ 403 |
| 4 | redaction gaps (bot tokens, JWTs, Bearer, AWS-style keys); unsanitised fields | new patterns + `safe_text` on every emitted string; card slugs shielded from over-redaction |
| 5 | unmeasured / stale kill switch shown as «не взведён» | Director: UNMEASURED, unreadable or >26 h ⇒ `None`; soft de-risk surfaced in both surfaces |
| 6 | release «IN_PRODUCTION» overclaims | `IN_PROD_TREE` only for code-sync paths; docs/site/tracker = `NOT_APPLICABLE`; restart caveat stated |
| 7 | mirror-read sections fresh by construction | observed = mirror's last fetch; STALE after 90 min |
| 8 | real capital $0 without a readable mode | $0 only with a readable paper execution mode |
| 9 | stale model repaints CRITICAL as a warning | CRITICAL keeps its colour + «stale» mark; kill-switch card marks staleness |
| 10 | deep links to cards the bot cannot resolve | link only when the production tracker resolves exactly that card; otherwise a named reason |
| 11–14 | server/builder/JWT robustness | non-dict pointer, read errors, `send_error` headers, socket timeout, `[::1]`, builder requires every served file, pointer via `atomic_save`, non-ASCII token ⇒ 403 |
| 15 | two verdicts on one screen; owner e-mails in a tracked plist | Director verdict dropped from the model; access config outside the repo |
| 16 | tests asserting the insecure behaviour / missing controls | replaced and added (journal W40) |

**Re-review of the two-listener server (architecture changed ⇒ reviewed again).** Verdict: no path to bundle
content without a valid JWT on the public listener, and a Cloudflare HTTP tunnel cannot reach the local
listener's no-JWT path (`cf-*` headers cannot be stripped by transform rules). Ten Low findings, all fixed:
duplicate `Content-Length` / duplicate `Host` / header-parse defects ⇒ 400 + close; HTTP/0.9 replies now carry
a status line and the security headers; the on-disk certs cache is removed (memory only) and a failed fetch
is not retried for 30 s; the access config is read with `O_NOFOLLOW` + `fstat` on one descriptor and is the
only source when present (environment only with `--allow-env-config`, and the wrapper unsets `MC_*`); the
public port is validated; `::1` dropped (AF_INET only); one build at a time (`flock`); wider proxy-header
refusal; `Cross-Origin-Resource-Policy: same-origin`.

**Fresh-session check (item 9 of [D]).** A session with no context explained every panel from screenshots
alone and answered the nine owner questions correctly. It also found that the restore drill showed «не
измерено» under a «healthy» backups badge while the drill ran daily: the model read a `status` key the file
never had. Fixed, along with its usability notes: UNKNOWN values are marked, live-admission reasons are shown,
and the Telegram button says it opens Telegram.

One meaning in both owner surfaces (found by the live consistency check, not the review): a fleet in WARNING
is «🟡 есть что проверить» in `/report` too — before, Telegram said «всё работает» for the same file.
