# EARN DEFI OWNER REMOTE — mobile product direction (Phase 7)

Turns the mobile view of the Visual OS into an **Owner Remote**: answer "what needs me?" in seconds,
see capital & strategies fast, act by voice. Desktop stays the full FounderOS/JARVIS graph environment —
**not simplified** to make mobile easier (verified: desktop Universe/Home/System/Why intact).

## Primary mobile navigation (bottom bar)
`ОБЗОР · КАПИТАЛ · [ГОЛОС] · СТРАТЕГИИ · СИСТЕМА` — 5 items, **VOICE central & raised** (high-emphasis).
Universe and WHY? are now **contextual** (reached from the graph hex / from an object's detail), not
permanent slots. DOM-verified: exactly 5 buttons, central one carries class `bn-voice`.

## CAPITAL surface (read-only, real state only)
Projector `build_mobile.py → capital.json` from `data/current_positions.json` (+ `capital_config.json`).
- **REAL / PAPER / SHADOW never confused.** Mode is `read_only_simulation` → **PAPER** track. Total
  ($100,000) sits under **exactly one** track column; REAL and SHADOW render **НЕТ ДАННЫХ / NOT AVAILABLE**
  (dimmed). Only `execution_mode == live` ever maps to REAL (guarded by a test).
- Total · deployed/cash bar ($80k / $20k) · accrued yield · allocation by protocol (usd, %, APY with
  **ДОК./EVIDENCED** vs **СТАТИК/STATIC** from `apy_source`, per-row track) · RiskPolicy v1.0 ✓ ·
  freshness (STALE) · provenance. Tap a protocol → detail sheet → WHY? where a real trace exists (aave).
- No invented financial state: missing → UNKNOWN/NOT AVAILABLE; every number carries `provenance`.

## STRATEGIES browser (canonical catalogue)
Projector `build_mobile.py → strategies.json` from `data/strategy_summary.json` (24 strategies).
- Cards: name, **tier** (T1/T2/T3, colour-coded), **lifecycle status** (the strategy's own `status`:
  active/research/advisory — not an invented lifecycle), target APY range, tail (max drawdown), type.
- Tier filter chips. Tap → detail sheet (provenance, tags, WHY where available). Marked **ADVISORY (paper)**.
- Does not create a second strategy DB or lifecycle — reads the canonical summary.

## VOICE — Owner input to existing Studio OS capabilities
Surface `surfaces.js::renderVoice` + classifier `classifyIntent`. STT: browser SpeechRecognition when
available, text fallback otherwise; **production STT path is local whisper on the Mac Mini** (already
installed at `/opt/homebrew/bin/whisper` + `~/.openclaw/whisper_server.py`) — no new paid API. Voice does
**not** create a hidden parallel task/memory system: it writes only a **local, explicitly non-canonical**
voice log (`localStorage`, labelled "not a canonical source"); canonical creation remains the owner-gated
backend step (`spa_core/owner_queue/intake.py`), which the remote does **not** perform.

### Safety zones (verified end-to-end through the live UI + a unit guard)
| Zone | Commands | Behaviour |
|---|---|---|
| **GREEN** | navigate · read-only query · WHY · draft idea/note | execute immediately |
| **YELLOW** | create canonical task · record decision | show interpreted **DRAFT + Owner Confirm**; on confirm, record locally and state canonical write is the owner-gated backend step — never auto-dispatched |
| **RED** | move capital · sign · enable live · change rate/RiskPolicy/limit · custody/keys | **BLOCKED** — never executes; may only create a proposal draft |

Provenance per interaction: original transcript · normalized command · timestamp · intent · zone ·
resulting entity/draft id · confirmation state · execution outcome.

### Security-critical bug found & fixed
First implementation anchored the Russian intent patterns with JS `\b`. **`\b` is ASCII-only** (Cyrillic
isn't `\w`), so `\bпереведи` never matched and **every Russian money/execution command silently fell into
the GREEN fallback** — a RED-leaks-to-GREEN safety hole. Fixed by removing the `\b` anchors (RED
over-matches toward BLOCK, the safe direction). Now guarded by `test_mobile_surfaces.py::test_voice_
classifier_safety` (19 phrases incl. 11 RED across RU/EN; node-absence fails loudly, not a silent skip).

## Verification (measured, not asserted)
- **Zero horizontal overflow** at 390 **and** 430, under real mobile emulation (Chrome DevTools
  `Emulation.setDeviceMetricsOverride mobile:true`), for capital/strategies/voice/home: `docOK=true`,
  `surfOK=true`, `offenders=0`. Also fixed a **pre-existing** HOME internal overflow (a `DIV.card` forced
  to 565px by `min-width:auto` on flex/grid items defeating `text-overflow:ellipsis`) — the earlier
  document-level check had missed it; added `min-width:0` on the flex/grid chain.
- **Voice pipeline** live-tested through the rendered UI: RED→block (no confirm), YELLOW→draft+confirm
  (never auto-executes), GREEN→immediate. 7/7 live + 19/19 unit.
- **No desktop regression:** Universe (radial graph), Home, System, Why render intact at 1440×900; sidebar
  reorganized (ЯДРО: Overview/Capital/Strategies/Voice · СТУДИЯ: graph nav · ИНТЕЛЛЕКТ: Why/Evidence).
- **Tests:** `test_read_model.py` 9 ✓ · `test_mobile_surfaces.py` 5 ✓ (projector invariants + classifier).

## Boundaries honoured
Read-only; UI ≠ canonical truth. No money path, no RiskPolicy/scheduler/execution change, no public-site
numbers (this is the local loopback tool, not `landing/`). No second backend/DB/source-of-truth. PAPER
never shown as REAL. No canonical writes from the browser.

## Files
New: `studio_shell/build_mobile.py`, `studio_shell/surfaces.js`, `studio_shell/capital.json`,
`studio_shell/strategies.json`, `studio_shell/test_mobile_surfaces.py`. Changed: `studio_shell/graph.js`
(capital/strategies/voice views + nav bridge + entity sheet + mobile BOTTOM), `studio_shell/graph.html`
(surface mounts + styling + central voice button + overflow guards).

## Run
`python3 studio_shell/build_mobile.py` then
`python3 -m http.server 8899 --bind 127.0.0.1 -d studio_shell` →
`http://127.0.0.1:8899/graph.html?view=capital|strategies|voice&lang=ru|en`.

Screenshots (`/tmp/sos_shots/`): `cdp_capital_390.png` · `cdp_strategies_390.png` · `cdp_voice_390.png` ·
`desk_capital.png` · `desk_universe.png`.
