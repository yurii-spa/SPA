#!/bin/bash
# push_final.sh — финальный пуш всего что не было запушено
# Протестирован: bash syntax OK, awk логика OK, файлы проверены
#
# Запуск: bash ~/Documents/SPA_Claude/scripts/push_final.sh

set -euo pipefail
cd "$(dirname "$0")/.."

# PAT fallback chain
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat | tr -d '[:space:]')
[[ "$PAT" == *"ТВОЙ"* || ${#PAT} -lt 10 ]] && PAT=""
[ -z "$PAT" ] && { echo "❌ PAT не найден (Keychain GITHUB_PAT_SPA)"; exit 1; }
echo "✅ PAT: ${#PAT} символов"

_push() {
  local label="$1" msg="$2"; shift 2
  local existing=()
  for f in "$@"; do [ -f "$f" ] && existing+=("$f"); done
  [ ${#existing[@]} -eq 0 ] && { echo "  ⚠️  $label — нет файлов, пропуск"; return; }
  echo -n "  → $label (${#existing[@]} файлов)... "
  python3 push_to_github.py --message "$msg" --pat "$PAT" --files "${existing[@]}" 2>&1 | tail -1
  sleep 1
}

echo ""
echo "── 1/5  Исправления P0/P1 ─────────────────────────────"
_push "DEPLOY.sh (исправленный awk)" \
  "fix: DEPLOY.sh — awk PID vs exit code bug, status now shows RUNNING/IDLE/CRASHED correctly" \
  scripts/DEPLOY.sh

_push "uptime_monitor fix (P0-1, 21 тест)" \
  "fix(P0-1): uptime_monitor exit 256 — returns 0 on DEGRADED, adds --strict flag | 21 tests" \
  spa_core/monitoring/uptime_monitor.py \
  tests/test_uptime_monitor.py \
  scripts/com.spa.uptime_monitor.plist

_push "Telegram plist fix (P0-2)" \
  "fix(P0-2): remove 3x plist conflict — canonical scripts/com.spa.bot_commands.plist (miniconda + spa_core.telegram.bot)" \
  scripts/com.spa.bot_commands.plist

_push "cloudflared + install_agents (P0-3, P1)" \
  "fix(P0-3,P1): cloudflared HOME env var + run_cloudflared.sh multi-path + install_agents auto-discover all 19 plists" \
  scripts/com.spa.cloudflared.plist \
  scripts/run_cloudflared.sh \
  scripts/install_agents.sh

echo ""
echo "── 2/5  Telegram Bot v2.0 ─────────────────────────────"
_push "Telegram Bot v2.0 (9 команд, 17 тестов)" \
  "feat: Telegram Bot v2.0 — /status /portfolio /today /week /agents /alerts /pause /resume /help | stdlib only | 17 tests" \
  spa_core/telegram/__init__.py \
  spa_core/telegram/bot.py \
  tests/test_telegram_bot_v2.py

echo ""
echo "── 3/5  Analytics v8.12-v8.18 (551 тест) ──────────────"
_push "v8.12 MEV + Borrower (141 тест)" \
  "feat(v8.12): MP-1106 MEV protection effectiveness + MP-1107 borrower concentration risk | 141 tests" \
  spa_core/analytics/defi_protocol_mev_protection_effectiveness_analyzer.py \
  spa_core/analytics/defi_protocol_borrower_concentration_risk_analyzer.py \
  spa_core/tests/test_defi_protocol_mev_protection_effectiveness_analyzer.py \
  spa_core/tests/test_defi_protocol_borrower_concentration_risk_analyzer.py

_push "v8.13 Insurance + Yield Harvesting (131 тест)" \
  "feat(v8.13): MP-1108 insurance fund adequacy + MP-1109 yield harvesting optimizer | 131 tests" \
  spa_core/analytics/defi_protocol_insurance_fund_adequacy_analyzer.py \
  spa_core/analytics/defi_protocol_yield_harvesting_frequency_optimizer.py \
  spa_core/tests/test_defi_protocol_insurance_fund_adequacy_analyzer.py \
  spa_core/tests/test_defi_protocol_yield_harvesting_frequency_optimizer.py

_push "v8.14 Lending + Cross-Chain (132 тест)" \
  "feat(v8.14): MP-1110 lending utilization elasticity + MP-1111 cross-chain yield basis risk | 132 tests" \
  spa_core/analytics/defi_protocol_lending_utilization_elasticity_analyzer.py \
  spa_core/analytics/defi_protocol_cross_chain_yield_basis_risk_analyzer.py \
  spa_core/tests/test_defi_protocol_lending_utilization_elasticity_analyzer.py \
  spa_core/tests/test_defi_protocol_cross_chain_yield_basis_risk_analyzer.py

_push "v8.15 Stablecoin + Emergency Withdrawal (207 тест)" \
  "feat(v8.15): MP-1148 stablecoin par redemption + MP-1149 emergency withdrawal pause risk | 207 tests" \
  spa_core/analytics/defi_protocol_stablecoin_par_redemption_capacity_analyzer.py \
  spa_core/analytics/defi_protocol_emergency_withdrawal_pause_risk_analyzer.py \
  spa_core/tests/test_defi_protocol_stablecoin_par_redemption_capacity_analyzer.py \
  spa_core/tests/test_defi_protocol_emergency_withdrawal_pause_risk_analyzer.py

_push "v8.16 Min Position + Keeper (207 тест)" \
  "feat(v8.16): MP-1150 min profitable position size + MP-1151 keeper reliability | 207 tests" \
  spa_core/analytics/defi_protocol_minimum_profitable_position_size_analyzer.py \
  spa_core/analytics/defi_protocol_auto_compound_keeper_reliability_analyzer.py \
  spa_core/tests/test_defi_protocol_minimum_profitable_position_size_analyzer.py \
  spa_core/tests/test_defi_protocol_auto_compound_keeper_reliability_analyzer.py

_push "v8.17 HWM + Crystallization (280 тест)" \
  "feat(v8.17): MP-1152 performance fee HWM + MP-1153 crystallization frequency | 280 tests" \
  spa_core/analytics/defi_protocol_performance_fee_high_water_mark_analyzer.py \
  spa_core/analytics/defi_protocol_performance_fee_crystallization_frequency_analyzer.py \
  spa_core/tests/test_defi_protocol_performance_fee_high_water_mark_analyzer.py \
  spa_core/tests/test_defi_protocol_performance_fee_crystallization_frequency_analyzer.py

_push "v8.18 Deposit Cap + Depositor Concentration (240 тест)" \
  "feat(v8.18): MP-1154 deposit cap headroom + MP-1155 depositor concentration | 240 tests" \
  spa_core/analytics/defi_protocol_deposit_cap_headroom_analyzer.py \
  spa_core/analytics/defi_protocol_depositor_concentration_analyzer.py \
  spa_core/tests/test_defi_protocol_deposit_cap_headroom_analyzer.py \
  spa_core/tests/test_defi_protocol_depositor_concentration_analyzer.py

_push "Module Registry (Tier-B 402)" \
  "feat: _module_registry.py Tier-B 402 modules + signal_aggregator (v8.12-v8.18)" \
  spa_core/analytics/_module_registry.py \
  spa_core/analytics/signal_aggregator.py

echo ""
echo "── 4/5  Документация + KANBAN ─────────────────────────"
_push "AGENT_AUDIT_V2 + KANBAN (854 done)" \
  "docs: AGENT_AUDIT_V2.md full gap analysis + KANBAN 854 done + sprint_log v8.18" \
  docs/AGENT_AUDIT_V2.md \
  KANBAN.json \
  sprint_log.md \
  CURRENT_STATE.md \
  RULES.md \
  .gitignore

echo ""
echo "── 5/5  Прочие plists и скрипты ───────────────────────"
_push "Plists и deploy-скрипты" \
  "chore: all plists + agent_status + push scripts + kill_switch reset" \
  scripts/com.spa.analytics_tier_c.plist \
  scripts/com.spa.daily-paper-report.plist \
  scripts/com.spa.checkpoint-7day.plist \
  scripts/com.spa.fund-api.plist \
  scripts/com.spa.autopush.plist \
  scripts/agent_status.sh \
  scripts/push_final.sh \
  data/kill_switch_active.json

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✅ push_final.sh DONE"
echo "══════════════════════════════════════════════════════"
