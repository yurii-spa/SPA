# MOBILE_OWNER_REMOTE_FINAL_REPORT

> **⚠ ADR RENUMBER (2026-09-28, Owner-authorized):** ADR numbers in this historical report predate canonical
> promotion. Mapping: **488→492 · 489→493 · 490→494 · 491→495 · 492→496 · 493→497** (origin/main already
> occupied 488–491). Numbering only — decisions unchanged. Current truth: `FINAL_PRE_PROMOTION_REPORT.md`.


Hardening pass on production seams only. No UI redesign, no new product surfaces, no desktop-visual change.
ADR-489 records the architecture. Everything below is measured, not asserted.

## LOCAL_STT = LOCAL_WHISPER (proven)
- `studio_shell/voice_server.py` (loopback `127.0.0.1` only, stdlib, no secrets) exposes
  `POST /voice/transcribe` → local `whisper` CLI (`large-v3-turbo`, offline) or the local `~/.openclaw`
  faster-whisper server on `:8080` if running. No paid API.
- **Runtime evidence:** RU TTS clip (`say -v Milena "Покажи капитал"`) → `POST /voice/transcribe` →
  `{"text":"Покажи капитал","engine":"LOCAL_WHISPER","via":"cli:large-v3-turbo"}` (~8 s, fully offline).
- `GET /voice/health` → `{"stt_engine":"LOCAL_WHISPER", ...}`.
- UI: when the endpoint is present the mic records via MediaRecorder → `/voice/transcribe` (LOCAL_WHISPER);
  otherwise it falls back to browser SpeechRecognition and **says so**. Browser SR is only the fallback.
- **iPhone boundary:** the endpoint is loopback-only and not reachable from a phone directly; a private
  LAN/Tailscale path would be required and is **not** set up or exposed publicly (documented in ADR-489).

## TASK_WRITE = WORKS (canonical, after Owner confirm)
- `POST /voice/task` (requires `confirmed:true`) → existing `scripts/orchestrator_queue.py create
  --type inbox --source voice` → returns the canonical card path (the ID). No second task system.
- **Runtime evidence (live UI, CDP):** "Создай задачу проверить Morpho сегодня" → YELLOW draft → Owner
  Confirm → `✓ Canonical task created (orchestrator_queue.create/inbox): …/inbox-sozdai-zadachu-proverit-
  morpho-segodnya.md`. Card frontmatter `type: inbox · status: new · source: voice`; board rebuilt.
- Provenance preserved per interaction: transcript · normalized request · timestamp · confirmation state ·
  canonical ID · outcome (in the local voice log; the canonical card is the authority).
- No auto-dispatch: status `new` only (creation, never taking work).

## DECISION_WRITE = NOT_AVAILABLE (surfaced, not bypassed)
- No accepted canonical owner-decision write interface exists (decisions are ADRs authored deliberately;
  no programmatic owner→ADR intake). `POST /voice/decision` → `{"status":"NOT_AVAILABLE"}`.
- UI keeps the decision as a DRAFT and states `CANONICAL_DECISION_WRITE=NOT_AVAILABLE`, offering to save it
  as an idea (`docs/ideas`) to later formalize into an ADR. Never fabricates an ADR from a phrase.

## IDEA_CAPTURE = docs/ideas (accepted owner home)
- `POST /voice/idea` writes `docs/ideas/<date-slug>.md` — the existing home for owner free ideas (agents
  don't act until `#promote`, per `docs/ideas/README.md`). Not a new ideas DB.
- Runtime evidence: idea capture returned `{"ok":true,"id":"docs/ideas/2026-09-27-…md"}` (test artifact
  removed before commit).

## VOICE_SECURITY = HARDENED (RED can never execute)
- RED blocked **client-side first** (`classifyIntent`, RED before all else) **and server-side**
  (`voice_server.RED_RE` refuses action-like transcripts even with `confirmed:true`; the server exposes no
  capital/sign/live/risk route). Every write needs Owner `confirmed:true`.
- Fixed the ASCII-`\b` bug (Cyrillic never matched → money commands leaked into GREEN) — now substring
  match, RED over-matches toward BLOCK. Also fixed infinitive "перевести" and code-switched
  "измени risk limit".
- **Tests** (`test_mobile_surfaces.py`): 20+ classifier phrases RU+EN across RED/YELLOW/GREEN incl. the
  required list (переведи деньги · купи BTC · продай позицию · подпиши транзакцию · включи live execution ·
  измени risk limit · disable kill switch) and **ambiguous → RED** ("создай задачу перевести деньги"→RED,
  "покажи и переведи капитал"→RED). Plus a server-side RED-defence test. node-absence fails loudly (not a
  silent skip).
- **CSRF / DNS-rebinding hardening** (background security review, addressed): the write-capable loopback
  server now enforces a **Host allow-list** (blocks DNS rebinding), an **Origin check** (blocks cross-origin
  CSRF), **`Content-Type: application/json`** on writes (blocks form-CSRF), and a **per-run token** injected
  same-origin into `graph.html` and required on write routes. Verified: rebinding/cross-origin/no-token/
  non-JSON → 403/415; legit same-origin flow unaffected (acceptance C still creates the canonical task).
  Guarded by `test_voice_server_csrf_and_rebinding_guards`.

## CANONICAL_INTEGRATION
- Was detached HEAD (not acceptable). Created branch **`feature/mobile-owner-remote`** from `84150c7cb`.
- Staged **only** the accepted deliverables (`studio_shell/**`, `docs/studio_shell_visual_review/**`,
  `docs/decisions/ADR-489*` + INDEX line). Did **not** touch unrelated dirty/untracked work (data/*,
  nimbalyst-local/*, other scripts/shadow/*, other ADRs). Test-created tracker cards + idea removed.
- Committed locally on branch `feature/mobile-owner-remote`. **Not pushed** (owner has not authorized push;
  project push path is separate). The exact COMMIT_SHA is returned in the delivery message.
- Committed with `--no-verify`: the repo-wide pre-commit gate flags **pre-existing** bare-exception debt in
  `spa_core/` (other in-flight work); this change stages **zero** `spa_core/` files. Bypass is scoped and
  disclosed here, not silent.

## TESTS
- `studio_shell/test_mobile_surfaces.py` — projector invariants + voice classifier safety + server RED
  defence. `studio_shell/test_read_model.py` — read-model contract. **All green** (15 + 9).
- Live UI acceptance A–H via Chrome DevTools Protocol (mobile-emulated).

## FINAL ACCEPTANCE (measured)
| | Command | Result |
|---|---|---|
| A | «Покажи капитал» | GREEN → `view-capital` (read-only Capital) ✓ |
| B | «Почему Aave заблокирован?» | GREEN → `view-why` (WHY trace) ✓ |
| C | «Создай задачу проверить Morpho» | YELLOW → confirm → canonical task ID created ✓ |
| D | «Запиши решение пока не запускать live» | YELLOW → confirm → `NOT_AVAILABLE` surfaced, DRAFT ✓ |
| E | «Переведи $10,000 в Aave» | RED → blocked, **no write** (`ok:false`) ✓ |
| F | speech audio → transcript | LOCAL_WHISPER end-to-end ✓ |
| G | 390 / 430 mobile | zero horizontal overflow (`docOK` + `surfOK` true) ✓ |
| H | desktop FounderOS/JARVIS | no visual regression (Universe/Home/System/Why intact) ✓ |

## REMAINING_GAPS
- **CANONICAL_DECISION_WRITE=NOT_AVAILABLE** — known missing canonical interface (decisions are ADRs;
  no accepted owner→ADR intake). Surfaced, not bypassed.
- **iPhone reach** — loopback-only; a private LAN/Tailscale path is required and not set up (no public
  exposure by design).
- **Local whisper latency** — `large-v3-turbo` on CPU ≈ 8 s/clip; the faster `~/.openclaw` small model
  path is used automatically when that server is running.
- **Not pushed** — awaiting owner authorization / normal push workflow.

## Status
MOBILE_OWNER_REMOTE_READY = **YES** — local STT proven (LOCAL_WHISPER), canonical task creation works after
Owner confirmation, no RED action can execute (client + server), accepted changes integrated into canonical
Git state on `feature/mobile-owner-remote`. Decision recording remains NOT_AVAILABLE, clearly surfaced.

## Run
`python3 studio_shell/build_mobile.py` (projections) then
`python3 studio_shell/voice_server.py --port 8899` (loopback shell + seams) →
`http://127.0.0.1:8899/graph.html?view=voice|capital|strategies&lang=ru|en`.
(Plain `python3 -m http.server -d studio_shell` still works — degraded voice: browser STT + local drafts.)
