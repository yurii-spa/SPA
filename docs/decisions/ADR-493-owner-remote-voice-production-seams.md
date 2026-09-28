# ADR-493: Owner Remote — voice production seams (local STT, canonical task, decision/idea)

- **Status:** ACCEPTED (loopback seams implemented, proven end-to-end) · 2026-09-27 · owner: @yurii
  > Renumbered before canonical promotion because origin/main already occupied the old ADR number (was ADR-489). Owner-authorized 2026-09-28; numbering change only — decision substance unchanged.
- **Scope:** `studio_shell/` mobile Owner Remote only. No money path, no RiskPolicy/execution change,
  no public-site numbers, no desktop-visual change. Read-only visual layer; UI ≠ canonical truth.

## Context

The Mobile Owner Remote (ADR-492 lineage) shipped a Voice UI with a GREEN/YELLOW/RED permission model,
but its production seams were stubs: browser SpeechRecognition (not proven local-first), and YELLOW
confirmations recorded only local drafts rather than reaching a canonical interface. This ADR closes the
seams **without** inventing new authorities.

## Decision

A single **loopback** server (`studio_shell/voice_server.py`, bound `127.0.0.1` only per
`.claude/rules/deployment.md` §8, stdlib only, no secrets) serves the static shell **and** exposes
narrow write seams. The browser talks only to this local origin.

| Seam | Interface | Result |
|---|---|---|
| **LOCAL STT** | `POST /voice/transcribe` → local `whisper` CLI (`large-v3-turbo`, offline), or the local `~/.openclaw` faster-whisper server on `127.0.0.1:8080` if up | `VOICE_STT_ENGINE=LOCAL_WHISPER`. No paid API. Proven: RU clip → «Покажи капитал» in ~8 s. |
| **CANONICAL TASK** | `POST /voice/task` (requires `confirmed:true`) → existing `scripts/orchestrator_queue.py create --type inbox --source voice` | returns the canonical card path (the ID). No second task system. Status `new` — creation only, never takes work / never dispatches. |
| **IDEA** | `POST /voice/idea` → `docs/ideas/<date-slug>.md` | the **accepted owner home** for free ideas (agents don't act until `#promote`, see `docs/ideas/README.md`). Not a new ideas DB. |
| **DECISION** | `POST /voice/decision` | **`CANONICAL_DECISION_WRITE=NOT_AVAILABLE`** — no accepted owner-decision write interface exists; kept as DRAFT (optionally saved as an idea to later formalize into an ADR). Never fabricates an ADR from a phrase. |

### Safety (RED can never execute)
- RED classification is **client-side first** (`classifyIntent`, RED checked before all else) **and**
  **server-side defence-in-depth** (`voice_server.RED_RE` refuses any action-like transcript even with
  `confirmed:true`). The server exposes **no** capital/sign/live/risk route at all.
- Every write requires an explicit Owner `confirmed:true`. No auto-dispatch.
- JS `\b` is ASCII-only and never matches Cyrillic — so `\b`-anchored Russian patterns silently failed and
  leaked money commands into GREEN. Fixed (substring match; RED over-matches toward BLOCK) and guarded by
  `test_mobile_surfaces.py` (RU+EN RED/YELLOW/GREEN incl. ambiguous "создай задачу перевести деньги" → RED).

### Browser-origin hardening (CSRF / DNS rebinding)
Loopback bind (rule #8) stops *network* reach but not a *browser-driven* cross-origin write: any page the
Owner visits can POST to `127.0.0.1`. Because this server performs canonical writes, it defends with
(1) a **Host allow-list** (`127.0.0.1`/`localhost`/`::1`) — a DNS-rebinding request carries the attacker
hostname → rejected; (2) an **Origin check** — cross-origin fetch → rejected; (3) **`Content-Type:
application/json`** required on writes — blocks `<form>` CSRF; (4) a **per-run token** injected into
`graph.html` and required on write routes — a cross-origin page cannot read the opaque HTML, so cannot
learn it. Verified: rebinding/cross-origin/no-token/non-JSON all rejected; same-origin flow unaffected
(`test_mobile_surfaces.py::test_voice_server_csrf_and_rebinding_guards`).

### Degraded mode (plain `http.server`)
When the loopback server is absent, the UI degrades honestly: browser STT + **local drafts only**, and says
so — it never pretends a canonical write happened.

## iPhone / network boundary
The endpoint is loopback-only by design and is **not** reachable from a phone directly. A phone would need
a private LAN/Tailscale path to `127.0.0.1`-equivalent; that is **not** set up here and is **not** exposed
publicly. Documented as the known boundary; no public exposure introduced.

## Consequences
- Voice can create real canonical tasks after Owner confirmation, with full provenance (transcript,
  normalized command, timestamp, confirmation, canonical ID, outcome).
- Decision recording remains a known missing canonical interface (surfaced, not bypassed).
- Acceptance A–H proven through the live UI + CDP (see `docs/studio_shell_visual_review/`).
